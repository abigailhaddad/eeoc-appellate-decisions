"""Fetch EEOC appellate-decision listing pages, politely, into a directory.

Usage:
  python3 -I scripts/fetch_pages.py <out_dir> (--pages A-B | --last-n N) [--delay 3]

Saves each page as NNNNN.html. With --last-n, page 0 is fetched first to read the
total ("1 - 10 of 115882"), which gives the last page; then pages L-N+1..L are fetched.
Writes <out_dir>/fetch_meta.json: {"total": T, "last_page": L, "pages": [...], ...}.

Every page must be HTTP 200, not a challenge page, show the same total as page 0, and
(except the last page) list 10 files. Network errors and 5xx are retried after 10, 30,
90 s; anything else stops the run (exit 2) so a half-fetched window is never used.
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

UA = "eeoc-decisions pipeline"
BASE = "https://www.eeoc.gov/federal-sector/appellate-decisions?appellate_keywords=&page={}"
WAITS = (10, 30, 90)
TOTAL_RE = re.compile(rb"(\d+) - (\d+) of (\d+)")


class FetchError(RuntimeError):
    pass


def _get(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read(), None
    except urllib.error.HTTPError as e:
        return e.code, b"", str(e)
    except Exception as e:
        return None, b"", repr(e)


def get_page(page, get=_get, sleep=time.sleep, waits=WAITS):
    """Return (html_bytes, (first, last, total)). Raises FetchError."""
    url = BASE.format(page)
    for i in range(len(waits) + 1):
        status, body, err = get(url)
        if status is not None and status < 500:
            break
        if i == len(waits):
            raise FetchError(f"page {page}: gave up after {i} retries: {err or status}")
        sleep(waits[i])
    if status != 200:
        raise FetchError(f"page {page}: HTTP {status} {err}")
    if b"Just a moment" in body[:5000] or b"challenge-platform" in body[:20000]:
        raise FetchError(f"page {page}: challenge page")
    m = TOTAL_RE.search(body)
    if not m:
        raise FetchError(f"page {page}: no 'N - M of T' counter (layout changed, or past the end)")
    return body, tuple(int(x) for x in m.groups())


def count_rows(body):
    return body.count(b"views-row")


def fetch(out_dir, pages=None, last_n=None, delay=3.0, get=_get, sleep=time.sleep):
    os.makedirs(out_dir, exist_ok=True)
    body0, (_, _, total) = get_page(0, get, sleep)
    last = (total - 1) // 10
    if last_n is not None:
        pages = range(max(0, last - last_n + 1), last + 1)
    pages = list(pages)
    beyond = [p for p in pages if p > last]
    if beyond:
        raise FetchError(f"requested pages past the last page {last}: {beyond[:5]}")
    for p in pages:
        if p == 0:
            body, (first, end, t) = body0, (1, min(10, total), total)
        else:
            sleep(delay)
            body, (first, end, t) = get_page(p, get, sleep)
        if t != total:
            raise FetchError(f"page {p}: total changed from {total} to {t} during the fetch; rerun")
        if first != p * 10 + 1:
            raise FetchError(f"page {p}: counter starts at {first}, expected {p * 10 + 1}")
        n = count_rows(body)
        want = end - first + 1
        if n != want:
            raise FetchError(f"page {p}: {n} rows on the page but the counter says {want}")
        with open(os.path.join(out_dir, f"{p:05d}.html"), "wb") as fh:
            fh.write(body)
    meta = {"total": total, "last_page": last, "pages": [pages[0], pages[-1]] if pages else [],
            "n_pages": len(pages),
            "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    with open(os.path.join(out_dir, "fetch_meta.json"), "w") as fh:
        json.dump(meta, fh, indent=1)
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pages", help="A-B inclusive")
    g.add_argument("--last-n", type=int)
    ap.add_argument("--delay", type=float, default=3.0)
    a = ap.parse_args()
    pages = None
    if a.pages:
        lo, hi = map(int, a.pages.split("-"))
        pages = range(lo, hi + 1)
    try:
        meta = fetch(a.out_dir, pages=pages, last_n=a.last_n, delay=a.delay)
    except FetchError as e:
        print(f"STOPPING: {e}", flush=True)
        return 2
    print(json.dumps(meta), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
