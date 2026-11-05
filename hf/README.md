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
---

# EEOC federal-sector appellate decisions

Every file listed on EEOC's appellate decisions page,
https://www.eeoc.gov/federal-sector/appellate-decisions, downloaded as-is.

A GitHub Actions job adds newly listed files daily
([code](https://github.com/abigailhaddad/eeoc-appellate-decisions)).

## What's here

`listing.parquet` (same rows as `listing.csv`; ID columns stored as text, so leading
zeros survive) is the index: one row per listed link. It started as a full crawl on
2026-11-01 (115,796 rows from 11,580 pages, matching the site's own total that day); the
daily job appends rows for new URLs. `page` and `position` are where the link was when
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

## Things to know before you use it

The number in a file name doesn't reliably identify the decision. 6,175 numbers appear in
more than one file. In a sample of 84 of those groups, 66 were the same decision posted
more than once: byte-identical copies, txt and PDF versions, or renamed copies. Seven were
a decision plus its posting order. Nine were different decisions in the same case, such
as an original decision and its later reconsideration, often under the identical file
name. Two had a file name pointing to the wrong case entirely (`05a40059.txt` is really
Request No. 05A50059). Use the case number printed in the document, and `sha256` to find
exact copies.

Other quirks of the source, kept as-is:

- 96 files have no usable number in the name. That includes truncated names like
  `01983-2.txt` and weekly bundle PDFs that hold many decisions each.
- 18 files are empty (0 bytes) on EEOC's site; rechecked 2026-11-05. For 5 of them a
  `.txt` with the same name has the text (`05a60527`, `05a60499`, `05a60248`, `01a60482`,
  `0120093445`). The other 13 have no copy under the same name: `0520110269.txt`,
  `01972934_burns_-`, `0120093457.r`, `0120081469`, `0120080695`, `0120063635`,
  `0420170003.txt`, `01976694.txt`, `0120161966.txt`, `0120160234.txt`, `01972830.txt`,
  `0120083883.txt`, `0120083780.txt`.
- Two listing rows link to the bare site root, `https://www.eeoc.gov`. They're in
  `listing.csv` but weren't downloaded.
- Older decisions name complainants in full, as they do on EEOC's site.

Code: https://github.com/abigailhaddad/eeoc-appellate-decisions
