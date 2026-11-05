"""Full recrawl of the listing, in chunks that fit a GitHub Actions job.

usage: recrawl.py <work_dir> <hf_repo_id> [--max-minutes M] [--max-pages N] [--delay S] [--force] [--no-upload]

The daily job only reads the end of the listing. This reads every page, which catches what that can't: new
files listed earlier in the listing, and listed files that disappeared.

Progress lives on the Hub (state/recrawl.json, state/recrawl_seen.txt.gz), so each run continues where the last
stopped. Once past the last page it rereads the tail, where rows move around, and compares URL sets:
  - URLs on the site but not in the index are appended to the listing; the daily job then downloads them.
  - URLs in the index not seen are checked directly on eeoc.gov and reported. Nothing is removed from the
    index or the dataset.
Results go to state/recrawl_report.json and one line in state/recrawl_history.jsonl.

A new crawl starts only if no crawl is under way and the last finished long enough ago, or with --force.
A crawl left unfinished for too long is abandoned and restarted, because the listing will have moved.

Exit codes: 0 finished or chunk saved (writes more=true to GITHUB_OUTPUT if pages remain); 2 stopped on an
error, progress kept; 3 finished, with URLs missing from the listing to look at.
"""

import argparse
import datetime
import gzip
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import pandas as pd
from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download
from huggingface_hub.utils import EntryNotFoundError

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch_pages  # noqa: E402
import parse_listing  # noqa: E402

STATE, SEEN = "state/recrawl.json", "state/recrawl_seen.txt.gz"
REPORT, HISTORY = "state/recrawl_report.json", "state/recrawl_history.jsonl"
TAIL_PAGES = 120  # reread at the end; rows near the end of the listing move
SAVE_EVERY = 500  # pages between progress saves
MIN_DAYS_BETWEEN = 20
ABANDON_AFTER_DAYS = 7
MAX_URL_CHECKS = 300
UA = fetch_pages.UA


def today():
    return datetime.date.today().isoformat()


def days_since(iso):
    return (datetime.date.today() - datetime.date.fromisoformat(iso)).days


def decide(state, force=False):
    """'new', 'continue' or 'skip', from the saved state."""
    if force or not state:
        return "new"
    if not state.get("finished"):
        return "new" if days_since(state["started"]) > ABANDON_AFTER_DAYS else "continue"
    return "new" if days_since(state["finished"]) >= MIN_DAYS_BETWEEN else "skip"


def new_state():
    return {"started": today(), "finished": None, "next_page": 0, "rows_seen": 0, "new_rows": [], "first_total": None,
            "last_total": None, "tail_done": False}


def read_page(page, known, seen, state, get=fetch_pages._get, sleep=time.sleep):
    """Fetch one page and record it. Unlike a window fetch, a total that changes mid-crawl is expected. Returns
    the site's total. Raises fetch_pages.FetchError on anything unexpected."""
    body, (first, end, total) = fetch_pages.get_page(page, get, sleep)
    want = end - first + 1
    n = fetch_pages.count_rows(body)
    if first != page * 10 + 1 or n != want:
        raise fetch_pages.FetchError(f"page {page}: starts at {first}, {n} rows, counter says {want}")
    rows = parse_listing.parse_page(body, page)
    for r in rows:
        if r["url"] not in seen:
            seen.add(r["url"])
            if r["url"] not in known:
                state["new_rows"].append(r)
    state["rows_seen"] += len(rows)
    state["first_total"] = state["first_total"] or total
    state["last_total"] = total
    return total


def crawl(state, known, seen, max_pages, delay, save, get=fetch_pages._get, sleep=time.sleep, deadline=None, clock=time.monotonic):
    """Read pages from next_page until max_pages or the deadline. Returns True once past the last page."""
    done = 0
    while True:
        if done >= max_pages or (deadline is not None and clock() >= deadline):
            return False
        total = read_page(state["next_page"], known, seen, state, get, sleep)
        last = (total - 1) // 10
        state["next_page"] += 1
        done += 1
        if done % SAVE_EVERY == 0:
            save()
        if state["next_page"] > last:
            return True
        sleep(delay)


def diff(index_urls, seen):
    """URLs in the index the crawl didn't see, leaving out non-file links."""
    return sorted(u for u in index_urls if u not in seen and "/sites/default/files/" in u)


def check_url(url):
    try:
        req = urllib.request.Request(urllib.parse.quote(url, safe=":/%"), method="HEAD", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return repr(e)[:80]


def build_report(state, index_rows, missing, statuses):
    final = len(index_rows) + len({r["url"] for r in state["new_rows"]})
    gone = [u for u, s in statuses.items() if s != 200]
    return {"started": state["started"], "finished": state["finished"], "site_total_first": state["first_total"],
            "site_total_last": state["last_total"], "rows_read": state["rows_seen"], "index_rows_before": len(index_rows),
            "index_rows_after": final, "matches_site_total": final == state["last_total"],
            "new_urls": sorted({r["url"] for r in state["new_rows"]}), "missing_from_listing": missing,
            "missing_checked": len(statuses), "missing_url_status": statuses, "missing_and_not_served": gone}


class Hub:
    def __init__(self, work, repo, upload):
        self.work, self.repo, self.upload, self.api = work, repo, upload, HfApi()

    def get(self, path, required=True):
        for attempt in range(6):
            try:
                return hf_hub_download(self.repo, path, repo_type="dataset", local_dir=self.work, force_download=True)
            except EntryNotFoundError:
                if required:
                    raise
                return None
            except Exception as e:
                print(f"download failed ({attempt + 1}/6): {str(e)[:120]}", flush=True)
                time.sleep(120)
        raise RuntimeError(f"could not download {path}")

    def put(self, files, msg, parent=None):
        """files: {path_in_repo: bytes}. Written locally too, so --no-upload runs can continue."""
        for path, data in files.items():
            os.makedirs(os.path.dirname(f"{self.work}/{path}"), exist_ok=True)
            with open(f"{self.work}/{path}", "wb") as fh:
                fh.write(data)
        if not self.upload:
            return
        ops = [CommitOperationAdd(path_in_repo=p, path_or_fileobj=d) for p, d in files.items()]
        for attempt in range(5):
            try:
                self.api.create_commit(repo_id=self.repo, repo_type="dataset", operations=ops, commit_message=msg,
                                       parent_commit=parent)
                return
            except Exception as e:
                print(f"upload failed ({attempt + 1}/5): {str(e)[:120]}", flush=True)
                if attempt == 4 or parent:
                    raise
                time.sleep(60 * (attempt + 1))


def pack_seen(seen):
    return gzip.compress("\n".join(sorted(seen)).encode())


def add_to_listing(hub, new_rows):
    """Append new URLs. parent_commit makes this fail rather than overwrite a listing the daily job just wrote."""
    for attempt in range(4):
        parent = hub.api.repo_info(hub.repo, repo_type="dataset").sha if hub.upload else None
        idx = pd.read_parquet(hub.get("listing.parquet"))
        have = set(idx.url)
        rows = [r for r in new_rows if r["url"] not in have]
        if not rows:
            return 0
        add = pd.DataFrame(rows, columns=[c for c in idx.columns if c != "first_seen"])
        add["first_seen"] = today()
        for c in ("page", "position"):
            add[c] = add[c].astype(idx[c].dtype)
        out = pd.concat([idx, add], ignore_index=True)
        buf = io.BytesIO()
        out.to_parquet(buf, index=False)
        csv = out.astype({c: str for c in out.columns if c not in ("page", "position")}).to_csv(index=False, quoting=1)
        try:
            hub.put({"listing.parquet": buf.getvalue(), "listing.csv": csv.encode()},
                    f"Recrawl {today()}: {len(rows)} new rows", parent=parent)
            return len(rows)
        except Exception as e:
            print(f"listing changed during the update, retrying: {str(e)[:120]}", flush=True)
            time.sleep(120)
    raise RuntimeError("could not update the listing")


def finish(hub, state, known, seen, delay, get=fetch_pages._get, sleep=time.sleep, check=check_url):
    if not state["tail_done"]:
        last = (read_page(0, known, seen, state, get, sleep) - 1) // 10  # the total may have grown since the last page
        for p in range(max(0, last - TAIL_PAGES + 1), last + 1):
            read_page(p, known, seen, state, get, sleep)
            sleep(delay)
        state["tail_done"] = True
    idx = pd.read_parquet(hub.get("listing.parquet"))
    missing = diff(set(idx.url), seen)
    statuses = {}
    for u in missing[:MAX_URL_CHECKS]:
        statuses[u] = check(u)
        sleep(delay)
    state["finished"] = today()
    report = build_report(state, list(idx.url), missing, statuses)
    added = add_to_listing(hub, state["new_rows"])
    old = hub.get(HISTORY, required=False)
    line = {k: v for k, v in report.items() if not isinstance(v, (list, dict))}
    line.update(new_urls=len(report["new_urls"]), missing=len(missing), not_served=len(report["missing_and_not_served"]), added=added)
    hist = (open(old, "rb").read() if old else b"") + (json.dumps(line) + "\n").encode()
    hub.put({STATE: json.dumps({**state, "new_rows": []}).encode(), REPORT: json.dumps(report, indent=1).encode(), HISTORY: hist},
            f"Recrawl finished {today()}")
    print(json.dumps(line), flush=True)
    return 3 if missing else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir")
    ap.add_argument("repo_id")
    ap.add_argument("--max-minutes", type=float, default=240, help="stop the chunk then; leaves time to finish inside a job")
    ap.add_argument("--max-pages", type=int, default=10 ** 6)
    ap.add_argument("--delay", type=float, default=3.0)
    ap.add_argument("--force", action="store_true", help="start a new crawl whatever the state says")
    ap.add_argument("--no-upload", action="store_true", help="keep state in work_dir; write nothing to the Hub")
    a = ap.parse_args()
    os.makedirs(a.work_dir, exist_ok=True)
    hub = Hub(a.work_dir, a.repo_id, not a.no_upload)
    local = f"{a.work_dir}/{STATE}"
    sp = local if a.no_upload and os.path.exists(local) else (None if a.no_upload else hub.get(STATE, required=False))
    state = json.load(open(sp)) if sp else None
    action = decide(state, a.force)
    print(f"recrawl: {action}; state {({k: v for k, v in state.items() if k != 'new_rows'} if state else None)}", flush=True)
    if action == "skip":
        return 0
    seen = set()
    if action == "new":
        state = new_state()
    else:
        p = f"{a.work_dir}/{SEEN}" if a.no_upload else hub.get(SEEN)
        seen = set(gzip.decompress(open(p, "rb").read()).decode().split("\n"))
    known = set(pd.read_parquet(hub.get("listing.parquet")).url)

    def save():
        hub.put({STATE: json.dumps(state).encode(), SEEN: pack_seen(seen)}, f"Recrawl progress: page {state['next_page']}")
        print(f"saved at page {state['next_page']}, {len(seen):,} URLs, {len(state['new_rows'])} new", flush=True)

    try:
        past_end = crawl(state, known, seen, a.max_pages, a.delay, save, deadline=time.monotonic() + a.max_minutes * 60)
    except fetch_pages.FetchError as e:
        save()
        print(f"STOPPING: {e}", flush=True)
        return 2
    save()
    if not past_end:
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a") as fh:
                fh.write("more=true\n")
        print(f"chunk done; continuing from page {state['next_page']}", flush=True)
        return 0
    try:
        return finish(hub, state, known, seen, a.delay)
    except fetch_pages.FetchError as e:
        save()
        print(f"STOPPING: {e}", flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
