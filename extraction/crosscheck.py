"""Whole-corpus checks that don't use the model: compare columns with plain text patterns, in both
directions, and write a random sample with its quotes as a proof file.

usage: crosscheck.py <work_dir> <results.jsonl> [more ...]
"""
import json, re, sys
import pandas as pd

work, *paths = sys.argv[1:]
d = pd.read_parquet(f"{work}/decisions.parquet")
R = {}
for p in paths:
    for l in open(p):
        r = json.loads(l)
        if r.get("fields"):
            R[r["sha256"]] = r["fields"]
ws = lambda t: re.sub(r"\s+", " ", t)
T = {s: ws(open(f"{work}/text/{s}.txt").read()) for s in d.sha256}


def body(t):
    """The decision without the standard rights paragraphs."""
    i = t.find("STATEMENT OF RIGHTS")
    return t[:i] if i > 0 else t


def compare(name, col, pat, flags=0):
    hit = d.sha256.map(lambda s: bool(re.search(pat, body(T[s]), flags)))
    c = d[col].fillna(False).astype(bool)
    print(f"{name:34} both {int((c & hit).sum()):>5} | column only {int((c & ~hit).sum()):>4} | text only {int((~c & hit).sum()):>4}")
    return d[c & ~hit].sha256.tolist(), d[~c & hit].sha256.tolist()


out = {}
out["race"] = compare("basis_race vs 'race ('", "basis_race", r"\brace\b", re.I)
out["sex"] = compare("basis_sex vs 'sex'", "basis_sex", r"\bsex\b|\bgender\b", re.I)
out["age"] = compare("basis_age vs 'age ('", "basis_age", r"\bage\s*\(|\bage\b,|\bage\b and|Age Discrimination", 0)
out["disability"] = compare("basis_disability vs disability", "basis_disability", r"\bdisabilit|Rehabilitation Act", re.I)
out["reprisal"] = compare("basis_reprisal vs reprisal", "basis_reprisal", r"\breprisal\b|\bretaliat", re.I)
out["changed"] = compare("changed vs REVERSE/VACATE/REMAND", "commission_changed_result", r"\bREVERS|\bVACAT|\bREMAND|\bMODIF(Y|IES)\b")
out["telework"] = compare("telework theme vs telework", "theme_telework", r"telework|remote work|work from home|return.to.office|work-from-home", re.I)
json.dump(out, open(f"{work}/crosscheck_ids.json", "w"))
s = pd.concat([d.sample(30, random_state=11), d[d.discrimination_found].sample(10, random_state=12),
               d[d.commission_changed_result].sample(10, random_state=13)]).drop_duplicates("sha256")
rows = []
for _, r in s.iterrows():
    f = R[r.sha256]
    rows.append({"url": r.url, "decision_date": r.decision_date, "agency": r.agency, "discrimination_found": r.discrimination_found,
                 "complainant_got_relief": r.complainant_got_relief, "commission_changed_result": r.commission_changed_result,
                 "bases_quote": f.get("bases_quote"), "outcome_quote": f.get("outcome_quote"),
                 "discrimination_found_quote": f.get("discrimination_found_quote"), "reason_quote": f.get("reason_quote")})
pd.DataFrame(rows).to_csv(f"{work}/proof_sample.csv", index=False)
print("proof sample", len(rows))
