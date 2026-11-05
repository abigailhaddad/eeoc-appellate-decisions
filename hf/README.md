---
license: other
license_name: us-government-public-records
pretty_name: EEOC federal-sector appellate decisions
language:
- en
configs:
- config_name: files
  default: true
  data_files: data/files-*.parquet
- config_name: listing
  data_files: listing.parquet
- config_name: decisions
  data_files: extracted/decisions.parquet
---

# EEOC federal-sector appellate decisions

Every file listed on EEOC's appellate decisions page,
https://www.eeoc.gov/federal-sector/appellate-decisions, downloaded as-is.

A GitHub Actions job adds newly listed files daily
([code](https://github.com/abigailhaddad/eeoc-appellate-decisions)).

## What's here

`listing.parquet` (same rows as `listing.csv`; ID columns stored as text, so leading
zeros survive) is the index: one row per listed link. It started as a full crawl on
2026-11-01, which matched the site's own total that day; the daily job appends rows for new URLs. `page` and `position` are where the link was when
first seen. EEOC's listing order shifts, so they aren't stable IDs; use `url`.

| column | meaning |
|---|---|
| `url` | link as listed |
| `file_name`, `folder`, `ext` | parsed from the URL |
| `posted_folder_date` | date in a `decisions/YYYY_MM_DD/` folder name. This is when EEOC posted the file, not when the decision was issued. |
| `numbers` | appeal/request numbers found in the file name |
| `numbers_loose`, `numbers_loose_rule` | numbers recovered from irregular names (`07-2014-0029-0500.pdf`, `closed0520150131.r.txt`), filled only when `numbers` is empty |
| `first_seen` | date the URL was first listed in a crawl (2026-11-01 for the original crawl) |

`data/files-*.parquet` holds one row per download attempt. The columns are `url`,
`file_name`, `page`, `position`, `http_status`, `content_type`, `n_bytes`, `sha256`,
`fetched_at`, `error`, and `content` (raw bytes of the .txt, .pdf or .docx; null if the
fetch failed). A URL that failed and was retried can show up more than once. Use the row
with `http_status` 200.

`state/uploaded.jsonl` has the same rows without `content`, plus the shard number:
a quick way to find a file without opening the shards. `state/runs.jsonl` has one line
per daily run: window, new rows, and whether the index matched the site's total.

`extracted/decisions.parquet` has fields read from each file posted since 2025 by
`claude-haiku-5-5`: one row per unique file, updated daily, with `url`,
`sha256`, `numbers`, `posted_month`, and these columns:

- Case: `decision_date`, `agency`, `appealing_party`, `date_formal_complaint`
- Complainant, as stated in the decision: `job_title`, `complainant_race_stated`, `complainant_sex_stated`,
  `disability_condition`, `representation`
- Bases: `basis_race`, `basis_sex`, `basis_disability`, `basis_age`, `basis_reprisal`
- Result: `discrimination_found`, `complainant_got_relief`, `commission_changed_result`,
  `aj_found_discrimination`, `agency_action_on_aj`
- Issues: `issue_performance_appraisal`, `issue_non_selection_or_promotion`, `theme_telework`

Only columns that passed testing against an answer key are included. These are model outputs, so check anything you rely on against the decision. The answer key was made by Claude
agents, not lawyers. `discrimination_found` means a finding exists in the case; it may predate this
decision, and false includes "not reached". Definitions and checks are in
[extraction/README.md](https://github.com/abigailhaddad/eeoc-appellate-decisions/blob/main/extraction/README.md),
and results by column in
[accuracy.csv](https://github.com/abigailhaddad/eeoc-appellate-decisions/blob/main/extraction/accuracy.csv).

## Things to know before you use it

The number in a file name doesn't reliably identify the decision. Many numbers appear in more than one
file. In a sample of those groups, most were the same decision posted more than once: byte-identical copies,
txt and PDF versions, or renamed copies. Others were a decision plus its posting order, different decisions in
the same case (such as an original decision and its later reconsideration, often under the identical file
name), or a file name pointing to the wrong case entirely (`05a40059.txt` is really Request No. 05A50059). Use the case number printed in the document, and `sha256` to find
exact copies.

EEOC's posting dates aren't decision dates. It posted almost nothing between December 2024 and January 2026
then posted decisions issued during that gap.

Other quirks of the source, kept as-is:

- Some files have no usable number in the name. That includes truncated names like
  `01983-2.txt` and weekly bundle PDFs that hold many decisions each.
- Some files are empty on EEOC's site (rechecked 2026-11-05). For `05a60527`, `05a60499`, `05a60248`, `01a60482`
  and `0120093445`, a `.txt` with the same name has the text. These have no copy under the same name:
  `0520110269.txt`, `01972934_burns_-`, `0120093457.r`, `0120081469`, `0120080695`, `0120063635`,
  `0420170003.txt`, `01976694.txt`, `0120161966.txt`, `0120160234.txt`, `01972830.txt`, `0120083883.txt`,
  `0120083780.txt`.
- A couple of listing rows link to the bare site root, `https://www.eeoc.gov`. They're in
  `listing.csv` but weren't downloaded.
- Older decisions name complainants in full, as they do on EEOC's site.
- Many 2025-26 PDFs have an image for page 1, apparently because the real name was redacted
  there, so plain text extraction misses the caption. `ocr_used` marks them in the extracted table.

Code: https://github.com/abigailhaddad/eeoc-appellate-decisions
