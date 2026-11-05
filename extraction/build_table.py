"""Turn batch results into the published table.

usage: build_table.py <work_dir> <listing.parquet> <results.jsonl> [more results.jsonl ...]

For each unique file: keep the last successful result, check it against the schema, check quotes
against the text, and compare decision_date with the date printed after FOR THE COMMISSION.
A value whose quote isn't in the text is blanked and named in values_dropped. Writes
<work_dir>/decisions.parquet and prints a report; nothing is uploaded.
"""
import json, os, re, sys, unicodedata
from collections import Counter

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from columns import clean, columns  # noqa: E402
from prompt import PROMPT_VERSION, MODEL, SCHEMA  # noqa: E402

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_RE = re.compile(rf"({MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})")
POSTED_RE = re.compile(r"/(20[2-9]\d)[-_](\d\d)[-_/]")  # year and month in the file's folder
MN = {m: i + 1 for i, m in enumerate(MONTHS.split("|"))}
QUOTED = {"decision_date": "decision_date_quote", "representation": "representation_quote",
          "theme_telework": "theme_telework_quote"}
USED = {"appealing_party", "aj_found_discrimination", "agency_action_on_aj", "discrimination_found", "representation"}
AGENCY_FIXES = {"Department of Treasury": "Department of the Treasury", "Department of Veteran Affairs": "Department of Veterans Affairs",
                "Department of the Veterans Affairs": "Department of Veterans Affairs", "Department of Navy": "Department of the Navy",
                "Department of Air Force": "Department of the Air Force", "United States Air Force": "Department of the Air Force",
                "United Postal Service": "United States Postal Service", "US Postal Service": "United States Postal Service",
                "U.S. Postal Service": "United States Postal Service", "United States Post Office": "United States Postal Service",
                "Health and Human Services": "Department of Health and Human Services",
                "Department of Health and Human Service": "Department of Health and Human Services",
                "U.S. Government Publishing Office": "United States Government Publishing Office"}


def parent_agency(a):
    a = re.sub(r"\s*\(.*$", "", a or "").strip().rstrip(",.")
    return AGENCY_FIXES.get(a, a)


def norm(s):
    s = unicodedata.normalize("NFKC", s).replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-").replace("­", "")
    s = re.sub(r"-\s*\n\s*", "-", s)
    return re.sub(r"\s+", " ", s).strip().lower().rstrip(".")


def printed_date(t):
    i = t.rfind("FOR THE COMMISSION")
    m = DATE_RE.search(t, i) if i >= 0 else None
    return f"{m.group(3)}-{MN[m.group(1)]:02d}-{int(m.group(2)):02d}" if m else None


def schema_errors(f):
    """Only the fields the published columns come from."""
    P = SCHEMA["properties"]
    e = []
    for k in USED:
        if clean(f.get(k)) not in P[k]["enum"]:
            e.append(f"{k}={f.get(k)}")
    for k in ("bases", "issue_categories"):
        if not isinstance(f.get(k), list):
            e.append(f"{k}={f.get(k)}")
    return e


def build_row(sha, fs, f, t, nums, ocr_used):
    """One published row. fs: the file records with this hash. f: model fields. t: the text."""
    doc = norm(t)
    out = columns(f)
    drops = []
    for col, q in QUOTED.items():
        v, quote = out[col], clean(f.get(q) or "")
        if v in ("", None, False, "not_stated"):
            continue
        if not quote or norm(quote) not in doc:
            drops.append(col)
            out[col] = None
    pd_ = printed_date(t)
    if pd_ and out["decision_date"] and pd_ != out["decision_date"]:
        out["decision_date"] = pd_  # the printed date wins
        drops.append("decision_date(replaced by printed date)")
    elif pd_ and not out["decision_date"]:
        out["decision_date"] = pd_
    out["agency"] = parent_agency(out["agency"])
    if clean(f.get("outcome")) == "reversed" and not out["commission_changed_result"]:
        out["commission_changed_result"] = True  # the model's own outcome says it reversed
        drops.append("commission_changed_result(set from outcome)")
    warn = []
    if out["aj_found_discrimination"] == "no_aj" and out["agency_action_on_aj"] != "no_aj_decision":
        out["aj_found_discrimination"] = None  # says no judge, but records what the agency did with a judge's decision
        drops.append("aj_found_discrimination(contradiction)")
    if out["date_formal_complaint"] and out["decision_date"] and out["date_formal_complaint"] > out["decision_date"]:
        warn.append("formal_complaint_dated_after_decision")
    first = fs[0]
    m0 = re.search(r"\b(20\d\d)\d{6}\b", first["file_name"])
    if m0 and out["decision_date"] and int(out["decision_date"][:4]) < int(m0.group(1)) - 1:  # numbers use the fiscal year
        warn.append("decision_date_before_appeal_year")
    m = POSTED_RE.search(first["url"])
    return {"sha256": sha, "url": first["url"], "file_name": first["file_name"], "n_urls": len(fs),
            "numbers": nums.get(first["url"], ""), "posted_month": f"{m.group(1)}-{m.group(2)}", **out,
            "values_dropped": ";".join(drops), "source_warnings": ";".join(warn), "ocr_used": ocr_used,
            "model": MODEL, "prompt_version": PROMPT_VERSION}


def main():
    work, listing, *paths = sys.argv[1:]
    res = {}
    for p in paths:
        for l in open(p):
            r = json.loads(l)
            if r.get("fields"):
                res[r["sha256"]] = r
    files = [json.loads(l) for l in open(f"{work}/files.jsonl")]
    by_sha = {}
    for f in files:
        by_sha.setdefault(f["sha256"], []).append(f)
    nums = pd.read_parquet(listing).drop_duplicates("url").set_index("url")["numbers"].to_dict()
    ocr = {json.loads(l)["sha256"] for l in open(f"{work}/text_log.jsonl") if json.loads(l).get("ocr_pages")}
    rows, rep, bad_schema = [], Counter(), []
    for sha, fs in by_sha.items():
        r = res.get(sha)
        if r is None:
            rep["no result"] += 1
            continue
        e = schema_errors(r["fields"])
        if e:
            bad_schema.append((sha[:10], e[:4]))
            rep["schema problem, row left out"] += 1
            continue
        rows.append(build_row(sha, fs, r["fields"], open(f"{work}/text/{sha}.txt").read(), nums, sha in ocr))
    df = pd.DataFrame(rows)
    df.to_parquet(f"{work}/decisions.parquet", index=False)
    print("unique files", len(by_sha), "| rows", len(df), "|", dict(rep))
    print("rows with a value changed or blanked:", int((df.values_dropped != "").sum()))
    print("schema problems:", bad_schema[:8])
    print("source warnings:", df.source_warnings[df.source_warnings != ""].value_counts().to_dict())
    print("--- contradictions to look at")
    d = df
    print("discrimination found, no relief:", int((d.discrimination_found & ~d.complainant_got_relief).sum()))
    print("Commission changed result, no relief:", int((d.commission_changed_result & ~d.complainant_got_relief).sum()))
    print("judge found discrimination, agency action none:", int(((d.aj_found_discrimination == "yes") & (d.agency_action_on_aj == "no_aj_decision")).sum()))
    print("aj_found blanked as contradictory:", int(d.values_dropped.str.contains("contradiction").sum()))
    fc = pd.to_datetime(d.date_formal_complaint, errors="coerce")
    dd = pd.to_datetime(d.decision_date, errors="coerce")
    print("unparseable decision_date:", int(dd.isna().sum()), "| formal complaint after decision:", int((fc > dd).sum()))
    print("decision year:", dd.dt.year.value_counts().sort_index().to_dict())
    print("--- totals")
    for c in ("discrimination_found", "complainant_got_relief", "commission_changed_result", "theme_telework",
              "basis_race", "basis_sex", "basis_disability", "basis_age", "basis_reprisal"):
        print(f"{c}: {int(d[c].fillna(False).astype(bool).sum())}")
    print("agencies, top:", d.agency.value_counts().head(8).to_dict(), "| distinct:", d.agency.nunique())


if __name__ == "__main__":
    main()
