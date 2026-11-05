"""Parse saved EEOC appellate-decision listing pages into one row per listed file.

Input: a directory of pages saved from
https://www.eeoc.gov/federal-sector/appellate-decisions?appellate_keywords=&page=N
named NNNNN.html (page number). Output: listing.csv plus a summary on stdout.

Usage: python3 -I scripts/parse_listing.py <pages_dir> <out_csv>
"""

import csv
import os
import re
import sys
from collections import Counter
from urllib.parse import unquote

import lxml.html

def loose_numbers(name):
    """Fallback for file names where the strict pattern finds nothing.

    Returns (numbers, rule). These come from the file NAME only; a sample of downloaded
    files showed names are sometimes wrong (e.g. 05a40059.txt is really 05A50059), so the
    authoritative number is the one printed in the document. Rules, checked on the full
    2026-11 listing (691 no-number rows, 595 recovered; 17 of 17 sampled recoveries
    matched the number printed in the document):
      hyphenated   07-2014-0029-0500, 20-2100-1907, 07-2006-0071_Dennis -> NN+YYYY+NNNN
      hyphen20     20-22001020 -> 2022001020
      prefixed     closed0520150131, e0520080226, posting_order0520160043
      concatenated 05200800100520080042 -> 0520080010;0520080042
    Not recovered (left empty): 9/11-digit names, truncated names like 01983-2.txt,
    weekly bundle PDFs, and other irregular names.
    """
    s = os.path.splitext(name)[0]
    # Not "-N" suffixes: the only one, 01-2013-0097-2.txt, is really Appeal No. 0120151282.
    m = re.match(r"(\d{2})-(\d{4})-(\d{4})(?:-\d{4})?(?=$|[ _.(])", s)
    if m:
        return ["".join(m.groups())], "hyphenated"
    m = re.fullmatch(r"(20)-(\d{8})", s)
    if m:
        return ["".join(m.groups())], "hyphen20"
    m = re.search(r"(?<=[A-Za-z])(0\d{9}|20\d{8})(?![0-9])", s)
    if m:
        return [m.group(1)], "prefixed"
    m = re.fullmatch(r"(\d{10})(\d{10})", s.split(".")[0])
    if m:
        return [m.group(1), m.group(2)], "concatenated"
    return [], ""


def parse_page(raw, page):
    """Rows for one saved listing page (bytes)."""
    rows = []
    tree = lxml.html.fromstring(raw)
    items = tree.xpath('//div[contains(@class, "views-row")]')
    for pos, item in enumerate(items):
        href = (item.xpath(".//a/@href") or [""])[0]
        name = unquote(href.rsplit("/", 1)[-1])
        folder = re.search(r"/files/(decisions/\d{4}_\d\d_\d\d|migrated_files/decisions|\d{4}-\d\d)/", href)
        posted = re.search(r"decisions/(\d{4})_(\d\d)_(\d\d)/", href)
        # Appeal/request numbers: 10-digit (2020+ style, e.g. 2020003602) or older
        # 8-10 character forms (e.g. 0120161017, 01A04522, 05980751); a file can list several.
        numbers = re.findall(r"(?<![0-9A-Za-z])(\d{10}|0\d[A-Za-z]?\d{5,7})(?![0-9])", name)
        loose, rule = loose_numbers(name) if not numbers else ([], "")
        rows.append({
            "page": page,
            "position": pos,
            "url": href,
            "file_name": name,
            "folder": folder.group(1) if folder else "",
            "posted_folder_date": "-".join(posted.groups()) if posted else "",
            "numbers": ";".join(dict.fromkeys(numbers)),
            "ext": os.path.splitext(name)[1].lower(),
            # Filled only when `numbers` is empty; see loose_numbers().
            "numbers_loose": ";".join(loose),
            "numbers_loose_rule": rule,
        })
    return rows


def parse_dir(pages_dir):
    """Returns (rows, files, empty_pages, bad_pages) for every NNNNN.html in pages_dir."""
    files = sorted(f for f in os.listdir(pages_dir) if re.fullmatch(r"\d{5}\.html", f))
    rows, empty_pages, bad_pages = [], [], []
    for f in files:
        page = int(f[:5])
        raw = open(os.path.join(pages_dir, f), "rb").read()
        if not raw:
            bad_pages.append(page)
            continue
        got = parse_page(raw, page)
        if not got:
            empty_pages.append(page)
        rows += got
    return rows, files, empty_pages, bad_pages


def write_csv(rows, out_csv):
    with open(out_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)


def main():
    pages_dir, out_csv = sys.argv[1], sys.argv[2]
    rows, files, empty_pages, bad_pages = parse_dir(pages_dir)
    write_csv(rows, out_csv)
    summarize(rows, files, empty_pages, bad_pages)


def summarize(rows, files, empty_pages, bad_pages):
    urls = Counter(r["url"] for r in rows)
    nums = Counter(n for r in rows for n in r["numbers"].split(";") if n)
    print(f"pages parsed: {len(files)} (first {files[0][:5]}, last {files[-1][:5]})")
    print(f"empty pages: {len(empty_pages)} {empty_pages[:10]}; zero-byte pages: {len(bad_pages)} {bad_pages[:10]}")
    print(f"rows: {len(rows):,}; unique URLs: {len(urls):,}; URLs listed more than once: {sum(1 for v in urls.values() if v > 1):,}")
    print(f"rows with no appeal number parsed: {sum(1 for r in rows if not r['numbers']):,}")
    print("  of those, recovered by loose rules:", dict(Counter(r["numbers_loose_rule"] for r in rows if not r["numbers"]).most_common()))
    print(f"appeal numbers in more than one file: {sum(1 for v in nums.values() if v > 1):,}")
    print("folders:", Counter(r["folder"].split("/")[0] if r["folder"].startswith("decisions/") else r["folder"] for r in rows).most_common(4))
    print("extensions:", Counter(r["ext"] for r in rows).most_common(5))


if __name__ == "__main__":
    main()
