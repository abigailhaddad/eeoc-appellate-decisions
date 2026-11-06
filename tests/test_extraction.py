"""Published-column logic (no API, no data files)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "extraction"))
import build_table  # noqa: E402
from columns import clean, columns  # noqa: E402

BASE = {"decision_date": "2026-01-02", "agency": "Department of Labor", "appealing_party": "complainant",
        "aj_found_discrimination": "no", "agency_action_on_aj": "fully_implemented",
        "commission_changed_result": False, "complainant_got_relief": False, "date_formal_complaint": "2024-01-02",
        "job_title": "Nurse", "complainant_race_stated": "", "complainant_sex_stated": "", "disability_condition": "",
        "representation": "not_stated", "theme_telework": False, "discrimination_found": "not_reached",
        "bases": ["race"], "issue_categories": ["performance_appraisal"]}


def test_columns_yes_only_for_discrimination():
    assert columns(BASE)["discrimination_found"] is False
    assert columns({**BASE, "discrimination_found": "yes"})["discrimination_found"] is True
    assert columns({**BASE, "discrimination_found": "no"})["discrimination_found"] is False


def test_columns_flags():
    c = columns(BASE)
    assert c["basis_race"] and not c["basis_sex"]
    assert c["issue_performance_appraisal"] and not c["issue_non_selection_or_promotion"]


def test_clean_strips_literal_quotes():
    assert clean('""') == "" and clean(' "x" ') == "x" and clean(3) == 3


def test_parent_agency():
    assert build_table.parent_agency("Department of War (Defense Logistics Agency),") == "Department of War"
    assert build_table.parent_agency("US Postal Service") == "United States Postal Service"
    assert build_table.parent_agency("United States Postal Service (Field Areas and Regions)") == "United States Postal Service"
    assert build_table.parent_agency("Peace Corps") == "Peace Corps"


def test_printed_date():
    t = "cites January 1, 2020.\nFOR THE COMMISSION:\nName\nMarch 4, 2026\nDate"
    assert build_table.printed_date(t) == "2026-03-04"
    assert build_table.printed_date("FOR THE COMMISSION:\n____\nDate") is None


def test_norm_handles_wraps_and_curly_quotes():
    assert build_table.norm("the Agency’s\nfinal  order.") == "the agency's final order"


def test_schema_errors_only_on_used_fields():
    assert build_table.schema_errors(BASE) == []
    assert build_table.schema_errors({**BASE, "agency_action_on_aj": "not_stated"})


FULL = {**BASE, "outcome": "affirmed", "decision_date_quote": "", "representation_quote": "", "theme_telework_quote": ""}


def rec(url, sha="a", status=200, n=5):
    return {"url": url, "sha256": sha, "http_status": status, "n_bytes": n}


def test_eligible_folders():
    u = __import__("update_extracted")
    by = u.eligible([rec("https://x/decisions/2026_11_04/a.pdf"), rec("https://x/2025-08/b.pdf", "b"),
                     rec("https://x/2027-01/c.pdf", "c"), rec("https://x/decisions/2024_12_09/d.pdf", "d"),
                     rec("https://x/migrated_files/decisions/e.txt", "e"), rec("https://x/2026-11/f.pdf", "f", 500),
                     rec("https://x/2026-11/g.pdf", "g", 200, 0)])
    assert sorted(by) == ["a", "b", "c"]


def test_extract_one_retries_bad_result():
    u = __import__("update_extracted")
    answers = iter([(None, 1000, 100), ({**FULL, "representation": "maybe"}, 1000, 100), (FULL, 1000, 100)])
    f, cost = u.extract_one("t", lambda t: next(answers), attempts=3)
    assert f == FULL and cost > 0


def test_extract_one_gives_up_and_still_counts_cost():
    u = __import__("update_extracted")
    f, cost = u.extract_one("t", lambda t: (None, 1000, 100), attempts=2)
    assert f is None and cost > 0


def test_extract_one_api_error_propagates():
    import pytest
    u = __import__("update_extracted")

    def boom(t):
        raise RuntimeError("credit balance too low")
    with pytest.raises(RuntimeError):
        u.extract_one("t", boom)


def test_merge_appends_and_refreshes_url_counts():
    import pandas as pd
    u = __import__("update_extracted")
    t = pd.DataFrame([{"sha256": "a", "n_urls": 1}])
    out = u.merge(t, [{"sha256": "b", "n_urls": 1}], {"a": [1, 2], "b": [1]})
    assert out.sha256.tolist() == ["a", "b"] and out.n_urls.tolist() == [2, 1]


def test_build_row_contradiction_and_warning():
    fs = [{"url": "https://x/decisions/2026_01_05/2026000001.pdf", "file_name": "2026000001.pdf"}]
    f = {**FULL, "aj_found_discrimination": "no_aj", "decision_date": "2006-09-21", "date_formal_complaint": "2020-01-01",
         "outcome": "reversed"}
    r = build_table.build_row("a", fs, f, "FOR THE COMMISSION:\nName\nSeptember 21, 2006\nDate", {}, False)
    assert r["aj_found_discrimination"] is None and r["commission_changed_result"] is True
    assert "decision_date_before_appeal_year" in r["source_warnings"]
    assert "formal_complaint_dated_after_decision" in r["source_warnings"]
    assert r["posted_month"] == "2026-01"


def test_number_map_falls_back_to_loose_numbers():
    import pandas as pd
    listing = pd.DataFrame([
        {"url": "u1", "numbers": "2025004177", "numbers_loose": ""},
        {"url": "u2", "numbers": "", "numbers_loose": "2024005105"},
        {"url": "u3", "numbers": "", "numbers_loose": ""},
        {"url": "u1", "numbers": "dup", "numbers_loose": ""},
    ])
    assert build_table.number_map(listing) == {"u1": "2025004177", "u2": "2024005105", "u3": ""}
    assert build_table.number_map(listing[["url", "numbers"]]) == {"u1": "2025004177", "u2": "", "u3": ""}


def test_fill_blank_numbers_only_touches_blank_rows():
    import pandas as pd
    t = pd.DataFrame([{"url": "u1", "numbers": ""}, {"url": "u2", "numbers": "keep"},
                      {"url": "u3", "numbers": None}, {"url": "u4", "numbers": ""}])
    out, n = build_table.fill_blank_numbers(t, {"u1": "111", "u2": "222", "u3": "333", "u4": ""})
    assert n == 2 and out.numbers.tolist() == ["111", "keep", "333", ""]
    assert t.numbers.tolist()[:2] == ["", "keep"] and pd.isna(t.numbers[2])  # the input table is not changed
    same, zero = build_table.fill_blank_numbers(out, {"u1": "999"})
    assert zero == 0 and same.numbers.tolist() == out.numbers.tolist()
