"""The published columns. A column is kept only if it scored at least 97% against the labeled
answer key across 183 decisions (see README.md). The model extracts more than this; the rest is
not published."""

DIRECT = ["decision_date", "agency", "appealing_party", "aj_found_discrimination", "agency_action_on_aj",
          "commission_changed_result", "complainant_got_relief", "date_formal_complaint", "job_title",
          "complainant_race_stated", "complainant_sex_stated", "disability_condition", "representation",
          "theme_telework"]
BASES = ["race", "sex", "disability", "age", "reprisal"]
ISSUES = ["performance_appraisal", "non_selection_or_promotion"]


def clean(v):
    return v.strip().strip('"').strip() if isinstance(v, str) else v


def columns(f):
    out = {k: clean(f[k]) for k in DIRECT}
    out["discrimination_found"] = f["discrimination_found"] == "yes"
    out.update({"basis_" + b: b in f["bases"] for b in BASES})
    out.update({"issue_" + i: i in f["issue_categories"] for i in ISSUES})
    return out
