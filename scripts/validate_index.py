"""Validate a listing.csv produced by parse_listing.py against the saved pages.

Usage:
  python3 -I scripts/validate_index.py <listing_csv> [--pages-dir DIR] [--last-page N]
                                       [--report OUT.txt]

Hard failures (exit 1):
  - zero-byte page files in --pages-dir
  - page files present in --pages-dir but with no rows in the CSV (empty/unparsed page)
  - gaps in the page-number sequence (pages missing between min and max)
  - any page with a row count other than 10, except the final page. The final page is
    --last-page if given (the true last page of the site listing), else the highest
    page number seen. A final page must have 1..10 rows.
  - rows with an empty URL
  - --last-page given and pages beyond it present, or pages up to it missing

Reported, not failures (they are real features of the source):
  - URLs listed more than once (with page/position of each occurrence)
  - rows with no parsed appeal number (full list written to --report)
  - counts by folder and extension
"""

import argparse
import csv
import os
import re
import sys
from collections import Counter, defaultdict


def folder_group(folder):
    if folder.startswith("decisions/"):
        return "decisions/YYYY_MM_DD"
    return folder or "(none)"


def validate(listing_csv, pages_dir=None, last_page=None):
    """Return (failures, report_lines). failures is a list of strings."""
    failures, report = [], []
    with open(listing_csv, newline="") as fh:
        rows = list(csv.DictReader(fh))

    by_page = defaultdict(list)
    for r in rows:
        by_page[int(r["page"])].append(r)
    pages = sorted(by_page)
    report.append(f"rows: {len(rows):,}; pages with rows: {len(pages):,}")
    if not pages:
        failures.append("CSV has no rows")
        return failures, report
    report.append(f"page range: {pages[0]}..{pages[-1]}")

    # Pages on disk: zero-byte and pages that produced no rows.
    if pages_dir:
        disk = {}
        for f in os.listdir(pages_dir):
            if re.fullmatch(r"\d{5}\.html", f):
                disk[int(f[:5])] = os.path.getsize(os.path.join(pages_dir, f))
        zero = sorted(p for p, s in disk.items() if s == 0)
        if zero:
            failures.append(f"zero-byte page files: {len(zero)} e.g. {zero[:20]}")
        no_rows = sorted(p for p, s in disk.items() if s > 0 and p not in by_page)
        if no_rows:
            failures.append(f"non-empty page files with no parsed rows: {len(no_rows)} e.g. {no_rows[:20]}")
        not_on_disk = sorted(set(by_page) - set(disk))
        if not_on_disk:
            failures.append(f"pages in CSV with no file in pages dir: {len(not_on_disk)} e.g. {not_on_disk[:20]}")
        report.append(f"page files on disk: {len(disk):,}; zero-byte: {len(zero)}; no rows: {len(no_rows)}")
        all_pages = set(by_page) | set(disk)
    else:
        all_pages = set(by_page)

    lo, hi = min(all_pages), max(all_pages)
    if lo != 0:
        failures.append(f"first page is {lo}, expected 0")
    gaps = sorted(set(range(lo, hi + 1)) - all_pages)
    if gaps:
        failures.append(f"missing pages in sequence: {len(gaps)} e.g. {gaps[:20]}")

    final = hi
    if last_page is not None:
        final = last_page
        beyond = sorted(p for p in all_pages if p > last_page)
        if beyond:
            failures.append(f"pages beyond --last-page {last_page}: {beyond[:20]}")
        if hi < last_page:
            failures.append(f"crawl incomplete: highest page {hi} < --last-page {last_page} "
                            f"({last_page - hi} pages missing at the end)")
    else:
        report.append(f"NOTE: --last-page not given; treating page {hi} as final (may be a partial crawl)")

    bad_counts = []
    for p in pages:
        n = len(by_page[p])
        if p == final:
            if not 1 <= n <= 10:
                bad_counts.append((p, n))
        elif n != 10:
            bad_counts.append((p, n))
    if bad_counts:
        failures.append(f"pages with unexpected row counts: {len(bad_counts)} e.g. {bad_counts[:20]}")
    expected = 10 * (len(pages) - 1) + len(by_page[final]) if final in by_page else None
    report.append(f"row-count check: {len(rows):,} rows vs expected {expected:,} "
                  f"(10 x {len(pages) - 1:,} full pages + {len(by_page.get(final, []))} on final page {final})"
                  if expected is not None else "row-count check: final page has no rows")

    empty_url = [(r["page"], r["position"]) for r in rows if not r["url"].strip()]
    if empty_url:
        failures.append(f"rows with empty URL: {len(empty_url)} e.g. {empty_url[:20]}")

    # Duplicate URLs: reported, not a failure.
    locs = defaultdict(list)
    for r in rows:
        locs[r["url"]].append(f"p{r['page']}#{r['position']}")
    dups = {u: l for u, l in locs.items() if len(l) > 1}
    report.append(f"unique URLs: {len(locs):,}; URLs listed more than once: {len(dups):,} "
                  f"(extra rows: {sum(len(l) - 1 for l in dups.values()):,})")
    for u, l in sorted(dups.items()):
        report.append(f"  DUP {u}  at {', '.join(l)}")

    no_num = [r for r in rows if not r["numbers"].strip()]
    report.append(f"rows with no parsed appeal number: {len(no_num):,}")
    for r in no_num:
        report.append(f"  NONUM p{r['page']}#{r['position']} {r['url']}")

    report.append("rows by folder:")
    for k, v in Counter(folder_group(r["folder"]) for r in rows).most_common():
        report.append(f"  {v:>8,}  {k}")
    report.append("rows by extension:")
    for k, v in Counter(r["ext"] or "(none)" for r in rows).most_common():
        report.append(f"  {v:>8,}  {k}")
    return failures, report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("listing_csv")
    ap.add_argument("--pages-dir")
    ap.add_argument("--last-page", type=int)
    ap.add_argument("--report", help="write full report (incl. every dup / no-number row) here")
    ap.add_argument("--max-print", type=int, default=25, help="max DUP/NONUM lines on stdout")
    a = ap.parse_args(argv)

    failures, report = validate(a.listing_csv, a.pages_dir, a.last_page)
    if a.report:
        with open(a.report, "w") as fh:
            fh.write("\n".join(report + [f"FAIL: {f}" for f in failures]) + "\n")
    shown = Counter()
    for line in report:
        kind = line.strip().split(" ", 1)[0]
        if kind in ("DUP", "NONUM"):
            shown[kind] += 1
            if shown[kind] > a.max_print:
                continue
        print(line)
    for kind, n in shown.items():
        if n > a.max_print:
            print(f"  ... {n - a.max_print} more {kind} lines (see --report)")
    for f in failures:
        print(f"FAIL: {f}")
    print("RESULT:", "FAIL" if failures else "OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
