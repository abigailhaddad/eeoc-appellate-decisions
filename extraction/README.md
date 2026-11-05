# Extracted fields

`claude-haiku-5-5` reads each decision posted in 2025-26 and fills in `prompt.py`. Only the columns in
`columns.py` are published: the ones that passed testing. The model extracts more than that (outcome, path to
decision, reasons, remedies, sanctions); those didn't pass and aren't published.

The numbers are in data files, not here: `accuracy.csv` has the test results for each column and
`run_summary.json` has the counts from the full run.

## Running it

```sh
python3 -I extraction/build_text.py WORK abigailhaddad/eeoc-appellate-decisions  # text; OCR for image pages
python3 -I extraction/batch.py submit WORK && python3 -I extraction/batch.py collect WORK
python3 -I extraction/build_table.py WORK LISTING.parquet WORK/results_full.jsonl
python3 -I extraction/crosscheck.py WORK WORK/results_full.jsonl
```

This is a one-time run, not part of the daily update, so newly posted decisions aren't in the table.

## How it was tested

The prompt was tested on separate sets of decisions it wasn't tuned on, mostly chosen at random, with a few
picked for rare cases or orders. The answers were labeled from the full text without seeing the model's
output. The labelers were Claude agents, one per decision: not lawyers, and they could share blind spots with
the model. Most disagreements weren't hand-checked. Wins are rare, so the win-side columns rest on few cases.

## What the columns mean

- `discrimination_found`: a finding of discrimination exists in the case, by the Commission or by a decision
  it left standing. It need not be new: some rows have a finding but no relief, mostly fee, remedy or
  compliance disputes after an earlier finding. False covers both "no discrimination" and "merits not reached".
- `complainant_got_relief`: this decision gave the complainant something, including a remand.
- `commission_changed_result`: the Commission reversed, vacated, remanded or modified the decision under
  review. It can go against the complainant. "Affirm, and remand for compliance" counts as no change.
- `agency`: parent agency, variants merged. `Department of War` is kept as printed, separate from
  `Department of Defense`.
- `basis_*`, `issue_*`: true if stated in the decision. `complainant_race_stated` and
  `complainant_sex_stated` are the words in the parentheses after the basis.

## Checks on the full run

- `decision_date` is checked against the date printed after FOR THE COMMISSION, and the printed date wins.
  Decisions that print no date are blank.
- `theme_telework` and `representation` values whose quote isn't in the text are blanked and named in
  `values_dropped`.
- `aj_found_discrimination` is blank where the model recorded no judge alongside a judge's decision.
- `commission_changed_result` is set to true where the model's own outcome said reversed.
- `source_warnings` flags errors printed in the decisions, kept as printed: formal complaints dated after the
  decision, and decision dates years before the appeal.
- `crosscheck.py` compares columns with text patterns in both directions.

Rows are unique files. A decision reposted as a different file appears twice.
