# Extracted fields

`claude-haiku-5-5` reads each decision posted in 2025-26 and fills in `prompt.py`. Only the columns in
`columns.py` are published: the ones that scored at least 97% in testing. The model extracts more than
that (outcome, path to decision, reasons, remedies, sanctions); those didn't pass and aren't published.

## Running it

```sh
python3 -I extraction/build_text.py WORK abigailhaddad/eeoc-appellate-decisions  # text; OCR for image pages
python3 -I extraction/batch.py submit WORK && python3 -I extraction/batch.py collect WORK
python3 -I extraction/build_table.py WORK LISTING.parquet WORK/results_full.jsonl
python3 -I extraction/crosscheck.py WORK WORK/results_full.jsonl
```

This is a one-time run (2026-11-05), not part of the daily update.

## How it was tested

Three test sets, 183 decisions in all, none used to tune the prompt that was tested: 54, 60 and 69,
of which 170 were chosen at random and 13 picked for rare cases or orders. The columns were first chosen
after the 54; the 60 and 69 came later. Each decision's
answers were labeled from the full text, without seeing the model's output. The labelers were Claude
agents, one per decision: not lawyers, and they could share blind spots with the model. Most
disagreements weren't hand-checked.

| column | match, of 183 | real cases found |
|---|---|---|
| `discrimination_found` | 100% | 8/8 |
| `commission_changed_result` | 100% | 16/16 |
| `date_formal_complaint`, `appealing_party` | 100% | |
| `basis_sex`, `basis_age` | 100% | 66/66, 50/50 |
| `decision_date` | 100% | |
| `complainant_got_relief` | 99.5% | 18/19 |
| `basis_race`, `basis_reprisal`, `basis_disability` | 99.5% | 63/64, 101/102, 72/73 |
| `job_title`, `issue_performance_appraisal`, `theme_telework` | 99.5% | |
| `agency`, `agency_action_on_aj`, `complainant_race_stated`, `complainant_sex_stated` | 98.9% | |
| `disability_condition`, `representation` | 98.4% | |
| `issue_non_selection_or_promotion`, `aj_found_discrimination` | 97.3% | |

Wins are rare, so the win-side figures rest on few cases: 19 decisions with relief, 8 with a finding of
discrimination. With 183 decisions a score of 97% could really be a point or two lower.

## What the columns mean

- `discrimination_found`: a finding of discrimination exists in the case, by the Commission or by a
  decision it left standing. It need not be new: 14 rows have a finding but no relief, mostly fee,
  remedy or compliance disputes after an earlier finding. False covers both "no discrimination" and
  "merits not reached".
- `complainant_got_relief`: this decision gave the complainant something, including a remand.
- `commission_changed_result`: the Commission reversed, vacated, remanded or modified the decision under
  review. It can go against the complainant (7 rows). "Affirm, and remand for compliance" counts as no change.
- `agency`: parent agency, variants merged. `Department of War` is kept as printed, separate from
  `Department of Defense`.
- `basis_*`, `issue_*`: true if stated in the decision. `complainant_race_stated` and
  `complainant_sex_stated` are the words in the parentheses after the basis.

## Checks on the full run

- Results: 5,744 of 5,744 unique files. 3 had a malformed value and were rerun.
- `decision_date` is checked against the date printed after FOR THE COMMISSION. The printed date wins (1
  row differed). 2 decisions print no date; they're blank.
- `theme_telework` and `representation` values whose quote isn't in the text are blanked and named in
  `values_dropped` (11 values).
- `aj_found_discrimination` is blank in 116 rows that recorded no judge alongside a judge's decision.
- `commission_changed_result` was set to true in 1 row where the model's own outcome said reversed.
- `source_warnings` flags errors printed in the decisions, kept as printed: 8 formal complaints dated after
  the decision, 2 decisions dated 2006 on 2026 appeals.
- `crosscheck.py` compares columns with text patterns in both directions. Sampling the mismatches for race
  found a few real misses, in line with 63/64 above.

Rows are unique files. A decision reposted as a different file appears twice.
