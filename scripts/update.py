"""Incremental update: find newly listed files and add them to the Hub dataset.

Usage:
  python3 -I scripts/update.py <work_dir> <hf_repo_id> [--window 60] [--max-window 960]
                               [--max-new 3000] [--dry-run]

Steps:
  1. Download listing.parquet and state/uploaded.jsonl from the Hub into <work_dir>.
  2. Fetch the last --window listing pages (scripts/fetch_pages.py). EEOC adds new files
     near the end of the listing. If any of the first 5 pages of the window has a URL
     not in the index, the window may not reach back far enough: double it and refetch,
     up to --max-window.
  3. New rows = window rows whose URL is not in the index. They are appended to the
     index with first_seen = today and their current page/position.
  4. Total check: index rows after the update should equal the site's own total. A
     mismatch means files were inserted before the window or removed somewhere; the
     run still adds what it found but exits 3 so a full recrawl gets scheduled.
  5. Fetch the new files (scripts/fetch_to_hf.py --push-state; each shard is committed
     with the state file), then upload listing.parquet, listing.csv and
     state/runs.jsonl, then reconcile the Hub against the state (scripts/reconcile_hf.py).

Exit codes: 0 ok; 2 stopped (fetch error, challenge page, too many new rows, window
could not reach the frontier); 3 finished but the total check failed; 1 reconcile failed.
"""

import argparse
import datetime
import io
import json
import os
import shutil
import subprocess
import sys

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import pandas as pd
from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch_pages  # noqa: E402
import parse_listing  # noqa: E402
import reconcile_hf  # noqa: E402

FRONTIER_PAGES = 5
FIRST_CRAWL_DATE = "2026-11-01"  # first_seen for rows from the original full crawl


def plan(index, window_rows, total):
    """Pure: given the index DataFrame, the parsed window rows and the site's total,
    return (new_rows, report). new_rows keeps every window row whose URL is new,
    including repeats of the same new URL (the index has one row per listed link)."""
    known = set(index["url"])
    new = [r for r in window_rows if r["url"] not in known]
    pages = sorted({r["page"] for r in window_rows})
    front = set(pages[:FRONTIER_PAGES])
    new_in_front = [r for r in new if r["page"] in front]
    report = {
        "window_pages": [pages[0], pages[-1]] if pages else [],
        "window_rows": len(window_rows),
        "new_rows": len(new),
        "new_urls": len({r["url"] for r in new}),
        "new_in_first_pages": len(new_in_front),
        "site_total": total,
        "index_rows_before": len(index),
        "index_rows_after": len(index) + len(new),
    }
    report["total_matches"] = report["index_rows_after"] == total
    return new, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir")
    ap.add_argument("repo_id")
    ap.add_argument("--window", type=int, default=60)
    ap.add_argument("--max-window", type=int, default=960)
    ap.add_argument("--max-new", type=int, default=3000)
    ap.add_argument("--delay", type=float, default=3.0)
    ap.add_argument("--dry-run", action="store_true", help="stop after the plan; upload nothing")
    ap.add_argument("--state-from", help="use this local uploaded.jsonl instead of the Hub copy (testing)")
    a = ap.parse_args()
    os.makedirs(a.work_dir, exist_ok=True)
    state_dir = os.path.join(a.work_dir, "state")
    os.makedirs(state_dir, exist_ok=True)
    today = datetime.date.today().isoformat()

    lp = hf_hub_download(a.repo_id, "listing.parquet", repo_type="dataset", local_dir=a.work_dir,
                         force_download=True)
    if a.state_from:
        shutil.copyfile(a.state_from, os.path.join(state_dir, "uploaded.jsonl"))
    else:
        sp = hf_hub_download(a.repo_id, reconcile_hf.STATE_PATH_IN_REPO, repo_type="dataset",
                             local_dir=a.work_dir, force_download=True)
        os.replace(sp, os.path.join(state_dir, "uploaded.jsonl"))
    index = pd.read_parquet(lp)
    if "first_seen" not in index.columns:
        index["first_seen"] = FIRST_CRAWL_DATE
    print(f"index: {len(index):,} rows", flush=True)

    window = a.window
    while True:
        pages_dir = os.path.join(a.work_dir, f"pages_{window}")
        try:
            meta = fetch_pages.fetch(pages_dir, last_n=window, delay=a.delay)
        except fetch_pages.FetchError as e:
            print(f"STOPPING: {e}", flush=True)
            return 2
        rows, *_ = parse_listing.parse_dir(pages_dir)
        new, report = plan(index, rows, meta["total"])
        print(json.dumps(report), flush=True)
        if report["new_in_first_pages"] == 0 or meta["pages"][0] == 0:
            break
        if window * 2 > a.max_window:
            print(f"STOPPING: new URLs reach the first {FRONTIER_PAGES} pages of a {window}-page window; "
                  "run a full recrawl", flush=True)
            return 2
        window *= 2
        print(f"widening the window to {window} pages", flush=True)

    if report["new_rows"] > a.max_new:
        print(f"STOPPING: {report['new_rows']} new rows is more than --max-new {a.max_new}; check by hand", flush=True)
        return 2
    if a.dry_run:
        for r in new[:20]:
            print("NEW", r["page"], r["position"], r["url"])
        return 0

    add = pd.DataFrame(new, columns=[c for c in index.columns if c != "first_seen"])
    add["first_seen"] = today
    for c in ("page", "position"):
        add[c] = add[c].astype(index[c].dtype)
    out = pd.concat([index, add], ignore_index=True)
    csv_path = os.path.join(a.work_dir, "listing.csv")
    out.astype({c: str for c in out.columns if c not in ("page", "position")}).to_csv(
        csv_path, index=False, quoting=1)

    rc = subprocess.call([sys.executable, "-I", os.path.join(HERE, "fetch_to_hf.py"), csv_path, state_dir,
                          a.repo_id, "--push-state", "--delay", "2"])
    if rc not in (0, 2):
        return rc
    fetch_stopped = rc == 2

    run = {"date": today, **report, "fetch_stopped": fetch_stopped,
           "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    api = HfApi()
    runs = b""
    if api.file_exists(a.repo_id, "state/runs.jsonl", repo_type="dataset"):
        runs = open(hf_hub_download(a.repo_id, "state/runs.jsonl", repo_type="dataset",
                                    local_dir=a.work_dir, force_download=True), "rb").read()
    pbuf = io.BytesIO()
    out.to_parquet(pbuf, index=False)
    api.create_commit(
        repo_id=a.repo_id, repo_type="dataset",
        commit_message=f"Update listing {today}: {report['new_rows']} new rows",
        operations=[
            CommitOperationAdd(path_in_repo="listing.parquet", path_or_fileobj=pbuf.getvalue()),
            CommitOperationAdd(path_in_repo="listing.csv", path_or_fileobj=csv_path),
            CommitOperationAdd(path_in_repo="state/runs.jsonl", path_or_fileobj=runs + (json.dumps(run) + "\n").encode()),
        ])
    print(f"uploaded listing: {len(out):,} rows", flush=True)

    failures, notes = reconcile_hf.reconcile(state_dir, a.repo_id, shards="2", listing=csv_path)
    for n in notes:
        print(n)
    for f in failures:
        print("FAIL", f)
    if failures:
        return 1
    if fetch_stopped:
        print("STOPPING: the file fetch stopped early (see above)")
        return 2
    if not report["total_matches"]:
        print(f"TOTAL MISMATCH: index has {report['index_rows_after']:,} rows, site says {report['site_total']:,}. "
              "Something was inserted before the window or removed; run a full recrawl.")
        return 3
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
