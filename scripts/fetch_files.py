"""Download every decision file listed in listing.csv, politely and resumably.

Usage:
  python3 -I scripts/fetch_files.py <listing_csv> <out_dir> [--delay 2] [--limit N]

Writes <out_dir>/files/<key> (key = first 20 hex chars of sha1(url)) and appends one JSON
line per attempt to <out_dir>/fetch_log.jsonl:
  url, key, status, content_type, bytes, sha256, fetched_at  (or url, key, error, fetched_at)
A URL with a logged 200 is skipped on rerun, so the script can be stopped and restarted.
Rows whose URL is not under /sites/default/files/ (e.g. the bare https://www.eeoc.gov link)
are skipped and counted.

Stops (exit 2) instead of retrying hard when:
  - a response looks like a challenge/HTML page for a file URL
  - 5 errors or non-200 responses in a row
Zero-byte 200 responses are logged, not treated as errors (EEOC really serves at least one:
migrated_files/decisions/0120093445).
"""

import argparse
import csv
import datetime
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "eeoc-decisions pipeline"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("listing_csv")
    ap.add_argument("out_dir")
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--limit", type=int, help="stop after this many new downloads")
    a = ap.parse_args()

    files_dir = os.path.join(a.out_dir, "files")
    os.makedirs(files_dir, exist_ok=True)
    log_path = os.path.join(a.out_dir, "fetch_log.jsonl")

    done = set()
    if os.path.exists(log_path):
        with open(log_path) as fh:
            for line in fh:
                d = json.loads(line)
                if d.get("status") == 200:
                    done.add(d["url"])

    with open(a.listing_csv, newline="") as fh:
        urls = list(dict.fromkeys(r["url"] for r in csv.DictReader(fh)))
    skipped = [u for u in urls if "/sites/default/files/" not in u]
    todo = [u for u in urls if "/sites/default/files/" in u and u not in done]
    print(f"unique URLs: {len(urls):,}; not file URLs (skipped): {len(skipped)} {skipped}; "
          f"already downloaded: {len(done):,}; to fetch: {len(todo):,}", flush=True)

    fetched, bad_streak = 0, 0
    with open(log_path, "a") as log:
        for u in todo:
            if a.limit is not None and fetched >= a.limit:
                break
            key = hashlib.sha1(u.encode()).hexdigest()[:20]
            rec = {"url": u, "key": key}
            try:
                req = urllib.request.Request(urllib.parse.quote(u, safe=":/%"), headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=120) as resp:
                    body, status = resp.read(), resp.status
                    ctype = resp.headers.get("Content-Type", "")
            except urllib.error.HTTPError as e:
                rec.update(status=e.code, error=str(e))
            except Exception as e:  # network errors: logged, counted toward the stop rule
                rec.update(error=repr(e))
            else:
                rec.update(status=status, content_type=ctype, bytes=len(body),
                           sha256=hashlib.sha256(body).hexdigest())
                if "text/html" in ctype or b"Just a moment" in body[:2000]:
                    rec.update(status=-1, error="looks like an HTML/challenge page")
                else:
                    with open(os.path.join(files_dir, key), "wb") as out:
                        out.write(body)
            rec["fetched_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
            log.write(json.dumps(rec) + "\n")
            log.flush()

            if rec.get("status") == 200:
                fetched, bad_streak = fetched + 1, 0
                if fetched % 500 == 0:
                    print(f"{fetched:,} downloaded this run ({rec['fetched_at']})", flush=True)
            else:
                bad_streak += 1
                print(f"PROBLEM {rec}", flush=True)
                if rec.get("status") == -1 or bad_streak >= 5:
                    print("STOPPING: challenge page or 5 failures in a row", flush=True)
                    return 2
            time.sleep(a.delay)
    print(f"done: {fetched:,} downloaded this run", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
