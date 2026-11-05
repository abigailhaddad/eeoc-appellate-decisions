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
