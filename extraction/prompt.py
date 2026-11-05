"""Extraction schema and prompt. Do not edit without re-running the labeled tests: the accuracy
figures in extraction/README.md were measured with exactly this text."""

MODEL = "claude-haiku-5-5"
EFFORT = "high"
MAX_TOKENS = 12000
PROMPT_VERSION = "v4"

S = lambda d="": {"type": "string", "description": d + " Empty string if none."}
Q = lambda what: {"type": "string",
                  "description": f"Verbatim sentence or phrase from the document supporting {what}; empty string if none."}
BASES = ["race", "color", "sex", "pregnancy", "sexual_orientation", "gender_identity", "religion",
         "national_origin", "age", "disability", "genetic_information", "reprisal", "equal_pay", "other"]
ISSUES = ["non_selection_or_promotion", "harassment_hostile_environment", "removal_or_termination",
          "suspension_or_discipline", "reasonable_accommodation_disability", "religious_accommodation",
          "pay_benefits_or_overtime", "reassignment_duties_or_schedule", "performance_appraisal", "leave_or_awol",
          "telework", "training", "medical_or_fitness_exam", "probationary_termination", "reduction_in_force",
          "constructive_discharge", "settlement_breach", "other"]
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "decision_date": S("Issuance date of THIS decision, YYYY-MM-DD: the date printed after 'FOR THE COMMISSION' and the signature, above the word 'Date'"),
        "decision_date_quote": Q("the decision date (copy the date as printed)"),
        "agency": S("Respondent department or agency from the caption, e.g. 'Department of Veterans Affairs' (not the person's name)"),
        "subagency": S("Component the complainant worked in, if named in the caption or the background, e.g. 'Veterans Health Administration', 'U.S. Customs and Border Protection', 'Transportation Security Administration'. A facility or office (e.g. 'VA Medical Center, Clarksburg') is not a component"),
        "path_to_decision": {"type": "string", "enum": [
            "dismissed_before_investigation", "agency_decision_no_hearing", "aj_summary_judgment",
            "aj_after_hearing", "aj_dismissal_or_sanction", "aj_class_certification", "mspb", "not_applicable_or_unclear"],
            "description": "How the underlying complaint was decided before reaching the Commission. aj_summary_judgment: an Administrative Judge decided without a hearing. aj_after_hearing: an AJ held a hearing. For a reconsideration request, describe the path of the underlying complaint if stated, else not_applicable_or_unclear."},
        "appealing_party": {"type": "string", "enum": ["complainant", "agency", "both", "unclear"]},
        "aj_found_discrimination": {"type": "string", "enum": ["yes", "no", "no_aj"],
            "description": "Did an Administrative Judge find discrimination on any claim?"},
        "agency_action_on_aj": {"type": "string", "enum": ["fully_implemented", "rejected_in_whole_or_part", "no_aj_decision"],
            "description": "What the agency's final order did with the AJ's decision. no_aj_decision if no AJ issued a decision on the merits or dismissal."},
        "commission_changed_result": {"type": "boolean",
            "description": "True if the Commission reversed, vacated, remanded or modified the decision directly under review, in whole or part. False if it affirmed it, denied the request or petition, or dismissed the appeal."},
        "complainant_got_relief": {"type": "boolean",
            "description": "True if this decision gives the complainant anything: a finding of discrimination, a remedy or a larger remedy, reinstating a dismissed claim, or a remand for investigation or hearing. If the complainant's own win below is simply affirmed, True."},
        "primary_reason": {"type": "string", "enum": [
            "untimely", "failure_to_state_claim", "no_jurisdiction_or_collateral_attack", "civil_action_or_settlement_bar",
            "reconsideration_criteria_not_met", "legitimate_reason_no_pretext", "harassment_not_severe_or_not_based_on_class",
            "accommodation_provided_or_not_required", "insufficient_evidence", "discrimination_established",
            "improper_dismissal", "agency_process_failure", "remedy_amount_dispute", "class_requirements", "other"],
            "description": "The single reason that decided this case. no_jurisdiction_or_collateral_attack: claim belongs in a grievance, MSPB or another forum, or attacks another proceeding. legitimate_reason_no_pretext: the agency gave a reason and the complainant did not show pretext. insufficient_evidence: no prima facie case, or the complainant offered no evidence. discrimination_established: the Commission or decision below found discrimination and that is upheld or entered. agency_process_failure: remand or relief because of an inadequate investigation, missing record, or failed obligation. remedy_amount_dispute: only the relief is at issue. If several apply, pick the ground for the main claim."},
        "reason_quote": Q("the main reason for the result"),
        "job_title": S("Complainant's job title as stated, e.g. 'Nurse', 'Mail Handler'"),
        "job_grade": S("Pay plan and grade as stated, e.g. 'GS-12', 'GS-0610-12', 'PS-05'"),
        "complainant_race_stated": S("Complainant's race as written in the parentheses after the basis, e.g. 'Black', 'Caucasian'"),
        "complainant_sex_stated": S("Complainant's sex as written in the parentheses after the basis, e.g. 'female'"),
        "challenges_diversity_program": {"type": "boolean",
            "description": "True only if the decision discusses a diversity, equity, inclusion or affirmative-action program or preference as part of a claim."},
        "disability_condition": S("The condition, if disability is a basis, e.g. 'PTSD', 'back injury'"),
        "accommodation_requested": {"type": "array", "items": {"type": "string", "enum": [
            "telework", "schedule_or_leave", "reassignment", "equipment_or_workspace", "duty_modification",
            "interpreter_or_communication", "religious_exemption_vaccine", "religious_schedule_or_dress", "other"]},
            "description": "Accommodations at issue; [] if none"},
        "harassment_conduct": {"type": "array", "items": {"type": "string", "enum": [
            "slurs_or_offensive_remarks", "sexual_conduct", "physical", "threats", "excessive_scrutiny_or_discipline",
            "exclusion_or_isolation", "workload_or_assignments", "other"]},
            "description": "Kinds of conduct alleged as harassment; [] if none"},
        "sanction_requested": {"type": "boolean", "description": "Did a party ask for sanctions or default judgment, or did the AJ raise them?"},
        "sanction_imposed": {"type": "string", "enum": [
            "none", "default_judgment", "dismissal_of_complaint", "adverse_inference_or_exclusion", "monetary", "other"]},
        "sanction_reason": S("Why sanctions were sought or imposed, e.g. 'late investigation', 'failed to produce complaint file', 'missed AJ order'; null if none"),
        "pecuniary_damages_usd": {"type": ["number", "null"], "description": "Pecuniary damages awarded, in dollars; null if none stated"},
        "attorney_fees_usd": {"type": ["number", "null"], "description": "Attorney's fees awarded or affirmed, in dollars; null if no amount"},
        "date_first_eeo_contact": S("Date of initial EEO counselor contact, YYYY-MM-DD"),
        "date_formal_complaint": S("Date the formal complaint was filed, YYYY-MM-DD"),
        "agency_quote": Q("the agency"),
        "decision_kind": {"type": "string", "enum": [
            "appeal_of_final_agency_decision", "appeal_of_final_order_after_AJ", "appeal_of_dismissal",
            "request_for_reconsideration", "petition_for_enforcement", "compliance_or_breach_of_settlement",
            "petition_mixed_case_mspb", "class_certification", "other"],
            "description": "appeal_of_dismissal: the agency (or AJ) dismissed the complaint or claims on procedural grounds and the complainant appeals that. petition_mixed_case_mspb: a 'Petition No.' asking the Commission to review an MSPB decision on discrimination. class_certification: the dispute is whether a class complaint should be certified or decertified."},
        "bases": {"type": "array", "items": {"type": "string", "enum": BASES},
                  "description": "Every basis the complainant alleged, as stated (include reprisal if alleged). Record pregnancy as 'pregnancy' and add 'sex' only if sex is also stated."},
        "bases_quote": Q("the bases"),
        "issue_categories": {"type": "array", "items": {"type": "string", "enum": ISSUES},
                             "description": "Categories of the personnel actions or conduct at issue"},
        "theme_covid_vaccine": {"type": "boolean", "description": "True only if a claim involves a COVID vaccine or testing requirement."},
        "class_complaint": {"type": "boolean", "description": "True if the complaint is a class complaint."},
        "outcome": {"type": "string", "enum": [
            "affirmed", "reversed", "modified", "vacated_and_remanded", "dismissal_affirmed",
            "dismissal_reversed_and_remanded", "appeal_dismissed", "reconsideration_denied",
            "reconsideration_granted", "petition_granted", "petition_denied", "concur_with_mspb",
            "differ_with_mspb", "mixed", "other"],
            "description": "What the Commission did. If the decision under review dismissed the complaint (procedural dismissal), use dismissal_affirmed or dismissal_reversed_and_remanded, not affirmed/reversed. appeal_dismissed: the Commission dismissed the appeal itself (e.g. untimely appeal, civil action filed). mixed: some claims affirmed and others reversed or remanded."},
        "outcome_quote": Q("the outcome (the operative 'we AFFIRM/REVERSE/DISMISS...' sentence)"),
        "discrimination_found": {"type": "string", "enum": ["yes", "no", "not_reached"],
                                 "description": "yes: the Commission, or the decision it affirmed, found discrimination or reprisal on at least one claim. no: the merits were decided and no discrimination was found. not_reached: the merits were not decided (dismissals, remands for investigation or hearing, procedural decisions)."},
        "discrimination_found_quote": Q("the discrimination finding"),
        "dismissal_reason": S("If a dismissal (of the complaint, claims or appeal) is at issue, the ground, e.g. 'untimely EEO counselor contact', 'failure to state a claim', 'untimely appeal', 'civil action filed'"),
        "compensatory_damages_usd": {"type": ["number", "null"],
                                     "description": "Non-pecuniary compensatory damages amount awarded, ordered or affirmed, in dollars; null if no amount is stated"},
        "compensatory_damages_quote": Q("the damages amount"),
        "remedies_ordered": {"type": "array", "items": {"type": "string", "enum": [
            "back_pay", "reinstatement_or_placement", "compensatory_damages", "attorneys_fees",
            "training", "consider_discipline", "posting_notice", "supplemental_investigation",
            "hearing", "other"]},
            "description": "Relief the Commission orders in THIS decision, from the ORDER section and its coded paragraphs. An 'ATTORNEY'S FEES (H....)' paragraph counts as attorneys_fees; 'POSTING ORDER (G....)' as posting_notice. Empty if nothing is ordered."},
        "representation": {"type": "string", "enum": ["stated_represented", "stated_pro_se", "not_stated"],
                           "description": "Only from case-specific text such as 'Complainant, through counsel' or 'Complainant, proceeding pro se'. The standard 'RIGHT TO REQUEST COUNSEL' and 'ATTORNEY'S FEES' paragraphs do not count."},
        "representation_quote": Q("the representation"),
        "executive_orders_cited": {"type": "array", "items": {"type": "string"},
                                   "description": "Numbers of every Executive Order the decision mentions, e.g. ['14043']"},
        "theme_workforce_reduction": {"type": "boolean",
            "description": "True only if a claim involves a RIF, reorganization, deferred resignation, probationary termination, DOGE, or a workforce-reduction executive order."},
        "theme_workforce_reduction_quote": Q("the workforce-reduction theme; empty when false"),
        "theme_telework": {"type": "boolean", "description": "True only if a claim involves telework, remote work, or return-to-office."},
        "theme_telework_quote": Q("the telework theme; empty when false"),
        "theme_dei_gender_identity": {"type": "boolean",
            "description": "True only if the decision mentions DEI programs or policy on gender identity (e.g. pronouns, bathrooms, 'gender ideology')."},
        "theme_dei_gender_identity_quote": Q("the DEI/gender-identity theme; empty when false"),
    },
}
SCHEMA["required"] = list(SCHEMA["properties"])

PROMPT = """You are reading one decision of the U.S. Equal Employment Opportunity Commission's Office of Federal Operations (federal-sector appeals). Record the fields with the tool `record_decision`.

Rules:
- Use only this document. If a field is not stated, use an empty string, null for dollar amounts, [] or "not_stated".
- Every *_quote is copied character for character from the document and is short: at most 15 consecutive words, on a single line of the document if you can, with no ending period added. Never paraphrase or skip words. When a boolean theme is false, its quote is empty.
- decision_date is the issuance date of THIS decision, not filing dates or the dates of earlier decisions.
- outcome and remedies_ordered describe what the Commission did in THIS decision.

<document>
{text}
</document>"""
