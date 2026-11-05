# Keeping the index current

`scripts/update.py` runs daily from `.github/workflows/update.yml` (needs the repo secret
`HF_TOKEN`). First live runs: 2026-11-05.

## What the source looks like

- The unfiltered listing (`/federal-sector/appellate-decisions?appellate_keywords=&page=N`)
  shows 10 files per page, about 11,590 pages. It is not sorted by date.
- New files land near the end, but not only at the very end, and existing rows move.
  Between the 2026-11-01 crawl and a fetch of the last 110 pages on 2026-11-05, the
  site total went from 115,796 to 115,882. All 86 new files were in those 110 pages:
  83 on the last 9 pages, 3 inserted on page 11555. About 900 of the older rows in the
  window had moved, some by 187-244 positions. Page/position is not an ID; use the URL.
- Posting lags issuance by weeks to well over a year. In a 10-file check (2026-11-04),
  a decision issued 2024-06-25 was posted in a `2026-01` folder; in a 56-file LLM pilot,
  the 2026 postings came about 1 to 24 months after issuance (posting month vs
  decision date, so rough to a month). (This note used to say "23 to 327
  days"; that range was wrong for 2024-2026 postings.) EEOC posted almost nothing between
  December 2024 and January 2026 (7 files with 2025 folder dates). Never infer issuance
  date from the folder date.
- The same decision is sometimes uploaded more than once as byte-identical files under
  different URLs. A small number of rows link to something that is not a decision file
  (e.g. page 2493 position 1 links to the bare site root `https://www.eeoc.gov`).

## Daily update (`scripts/update.py`)

1. Download `listing.parquet` and `state/uploaded.jsonl` from the Hub.
2. Fetch the last 60 pages (`scripts/fetch_pages.py`, 3 s apart, neutral User-Agent).
   Page 0 gives the site total, which gives the last page. Every page must be HTTP 200,
   not a challenge page, show the same total, start at the right row number, and list
   as many files as its counter says; otherwise the run stops (exit 2). Network errors
   and 5xx are retried after 10, 30, 90 s.
3. New rows = window rows whose URL is not in the index (sets, not positions). If any
   of the first 5 pages of the window has a new URL, the window may be too short: it
   doubles, up to 960 pages, then stops.
4. Total check: index rows + new rows must equal the site total. If not, something was
   inserted before the window or removed; the run adds what it found and exits 3.
   What it can't see: a removal and an insertion that cancel out. A full recrawl
   catches those.
5. New files are fetched by `scripts/fetch_to_hf.py --push-state`. EEOC's server often
   drops large files partway (a 4.6 MB PDF failed 4 full retries, and `curl` too), so
   downloads resume with Range requests and check the final size. Each shard is
   committed in one Hub commit together with `state/uploaded.jsonl`, and a shard that
   already exists is never overwritten. More than 3,000 new rows stops the run for a
   look by hand.
6. `listing.parquet`, `listing.csv` and `state/runs.jsonl` (one line per run) are
   uploaded in one commit. New rows get `first_seen` = run date; rows from the original
   crawl get 2026-11-01.
7. `scripts/reconcile_hf.py` checks the Hub against the state: same shard set, and for
   the last 2 shards the same (url, status, sha256) rows in the same order; plus every
   listing file URL has a state line. `--shards all` checks every shard (passed on
   2026-11-05 for all 117 shards, 115,798 rows; a deleted line and a changed hash were
   both caught in a test).

## Monthly full recrawl (`scripts/recrawl.py`)

The daily job can't see a file listed early in the listing, or a removal and an insertion that cancel out. A
full crawl can, but it takes longer than a GitHub Actions job may run and EEOC posts during it. So it runs in
chunks: `.github/workflows/recrawl.yml` reads pages, saves its place to `state/recrawl.json` on the Hub, and
starts the next chunk. Unlike a window fetch, a total that changes mid-crawl is expected. Rows shift while it
runs, so it compares URL sets, rereads the tail at the end, and checks anything still missing directly on
eeoc.gov. New URLs go into the listing for the daily job to download. Nothing is removed from the index or the
dataset: missing URLs are reported in `state/recrawl_report.json`, and the run opens an issue.

If the daily job exits 3, start this by hand with the `force` input.

## What to alert on (open an issue)

- Any `validate_index.py` hard failure (zero-byte page, page without rows, wrong row
  count on a non-final page, gaps, empty URL).
- Fetch failures: non-200, Cloudflare/challenge page, HTML with no `views-row` items.
- L decreased, or grew by much more than the usual weekly amount.
- No overlap between the window and the previous index (frontier lost).
- URLs that were in the previous index vanished from a full re-crawl (removals).
- Zero new URLs for 3+ weeks (site may have changed layout or sort).
- Spikes in rows with no parsed appeal number, or new folder patterns / extensions.
- Parser yield change: a page with HTML but fewer than 10 rows that is not the last page.

## Current local snapshot (full crawl finished 2026-11-01)

`data/listing_pages` holds pages 0 to 11579. Page 11579 reads "115791 - 115796 of
115796", which matches the total on page 0 when the crawl started. That gives 115,796
rows: 10 on every page except 6 on the last, with no zero-byte pages. The crawler also
fetched pages 11580-11584 past the end. Each says "No results found for the search", and
they are moved to `data/listing_pages_overrun/`. `validate_index.py --last-page 11579`
passes. There are 115,795 unique URLs. The one repeated URL is the bare site root
(pages 2493 and 2651).

### Rows with no number in the file name (691)

`parse_listing.py` now adds `numbers_loose` / `numbers_loose_rule`. They are filled only
when `numbers` is empty, and every existing column is unchanged. The new columns recover
595 of the 691 rows:

| rule | rows | example |
|---|---|---|
| hyphenated | 494 | `07-2014-0029-0500.pdf` -> 0720140029 |
| prefixed | 87 | `closed0520150131.r.txt` -> 0520150131 |
| concatenated | 12 | `05200800100520080042.txt` -> 0520080010;0520080042 |
| hyphen20 | 2 | `20-22001020.pdf` -> 2022001020 |

To check the rules, I downloaded 18 files covering every rule. In 17, the recovered
number matches the "Appeal/Request No." printed in the document. The 18th,
`01-2013-0097-2.txt`, is really Appeal No. 0120151282, a different case. It was the only
"-N" name, so that variant is now excluded. The other 96 rows (9- or 11-digit names,
truncated names like `01983-2.txt`, weekly bundle PDFs such as `Redacted OFO Decisions
03-05-2018 through 03-09-2018.pdf`, and other irregular names) need the number read from
the document.

### Appeal numbers shared by more than one file (6,175 numbers, 13,064 rows)

The listing alone can't settle these. The file name and folder don't tell you whether
two files are the same decision. For a fixed-seed sample of 84 groups (12 from each of 7
file-name types, 207 files), I downloaded the files and compared them by SHA-256 and by
text. For every group whose files disagreed on date or decision type, I also read the
header by hand.

| outcome | groups |
|---|---|
| same decision, byte-identical reposts | 22 |
| same decision, text differs (txt vs PDF, plain file adds a title line, renamed `... DEC.pdf`) | 44 |
| a decision plus its separate posting order | 7 |
| different decisions in one case under the same number, often the identical file name (original, then reconsideration or enforcement) | 9 |
| file name's number belongs to a different case | 2 |

Examples:
- `2022001961.pdf`. The decisions/2024_02_05 copy is the original decision. The
  2024_05_22 and 2024_12_09 copies are the reconsideration (Request No. 2024000609).
- `05a40059.txt` is really Request No. 05A50059 (*Makosky v. Agriculture*). The real
  05A40059 is `05a40059_r.txt`.
- `_r` / `.r` files are not redacted versions. The plain file just adds one title line.
- `migrated_files/decisions/0120093445` (no extension) is a 0-byte HTTP 200 response.
  `0120093445.txt` has the text.

These are sample counts, not rates for all 6,175 groups. The 66 "same decision" groups
were classed by hash, or by text similarity plus matching header fields, and only some
were read in full. Proof file: `data/checks_2026-11-02/shared_numbers_sample_proof.csv` (gitignored), with
URL, page/position, SHA-256 and the printed case-number line for all 207 files.

Consequence: **identify a decision by the number and decision type printed in the
document, not by its file name**. Keep every URL as a row, add the content SHA-256 to
mark exact duplicates, and add fields parsed from the document header (Request/Appeal/
Petition No., decision type, decision date).

## Downloading the files

`scripts/fetch_files.py data/listing.csv data/` downloads each file URL once. It can be
stopped and restarted (a URL with a logged 200 is skipped), waits 2 s between requests,
uses a neutral User-Agent, and stops on a challenge page or 5 failures in a row. Every
attempt is logged to `data/fetch_log.jsonl` with its SHA-256. On 13 sample URLs, a rerun
resumed correctly and every hash matched an earlier independent fetch. Cost at 2 s per
request: about 115,800 requests, roughly 64 hours. From the 207-file sample, size is
about 7 GB (txt ~14 KB, PDF ~180 KB on average), a rough estimate.

## TODO

- Hard-fail or separately flag rows whose URL is not under `/sites/default/files/`.
- After the full download: parse each document's header (case numbers, decision type,
  date), group by SHA-256, and classify every shared-number group. Spot-check each class
  against the documents.
- Fill the 96 still-unnumbered rows from document text. Split the weekly bundle PDFs.
- `validate_index.py` fails when overrun pages past `--last-page` are left in the pages
  dir. Either move them aside (done by hand on 2026-11-02) or teach the validator to
  accept "No results found" pages past the end.
