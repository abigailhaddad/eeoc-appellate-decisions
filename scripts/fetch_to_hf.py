"""Download every decision file in listing.csv and stream it to a Hugging Face dataset.

Usage:
  python3 -I scripts/fetch_to_hf.py <listing_csv> <state_dir> <hf_repo_id>
                                    [--shard-size 1000] [--delay 2] [--limit N]

Files are fetched one at a time (2 s apart, neutral User-Agent) into an in-memory batch.
Each full batch is written as one Parquet shard, uploaded to
<hf_repo_id>/data/files-NNNNN.parquet, and then the local temp file is deleted, so the
file contents never accumulate on this machine.

Each shard row is one fetch attempt:
  url, file_name, page, position, http_status, content_type, n_bytes, sha256,
  fetched_at, error, content (raw bytes; null when the fetch failed)
page/position are the URL's first appearance in listing.csv.

Resume state is <state_dir>/uploaded.jsonl, one line per attempt (no contents). Lines are
written only after their shard's upload succeeds. A rerun skips URLs with a logged 200
and retries the rest, so a crash loses at most one unfinished batch. A failed URL that is
retried can appear in more than one shard; use the row with http_status 200.

Dropped connections resume with Range requests; network errors, short bodies and 5xx are
retried. Stops (exit 2) on a challenge/HTML page for a file URL or 5 failures in a row, after
uploading the partial batch. Zero-byte 200s are kept (EEOC really serves at least one:
migrated_files/decisions/0120093445).
"""

import argparse
import csv
import datetime
import hashlib
import http.client
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")  # keep the run log readable

import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import CommitOperationAdd, HfApi

UA = "eeoc-decisions pipeline"
STATE_PATH_IN_REPO = "state/uploaded.jsonl"
SCHEMA = pa.schema([
    ("url", pa.string()), ("file_name", pa.string()), ("page", pa.int32()), ("position", pa.int32()),
    ("http_status", pa.int32()), ("content_type", pa.string()), ("n_bytes", pa.int64()),
    ("sha256", pa.string()), ("fetched_at", pa.string()), ("error", pa.string()),
    ("content", pa.binary()),
])


RETRY_WAITS = (10, 30, 90)  # seconds before retries 1-3 of a network error, short body, or 5xx


MAX_RESUMES = 20  # Range requests per fetch; EEOC's server often drops large files partway


def _get(url, opener=urllib.request.urlopen, pause=2.0, sleep=time.sleep):
    """Fetch url, resuming with Range requests when the connection drops partway. The
    ETag is sent as If-Range, so a file that changed mid-download restarts from zero.
    Returns (status, content_type, body, error)."""
    quoted = urllib.parse.quote(url, safe=":/%")
    body, status, ctype, total, etag = b"", None, "", None, None
    last_err = None
    for _ in range(MAX_RESUMES + 1):
        headers = {"User-Agent": UA}
        if body:
            headers["Range"] = f"bytes={len(body)}-"
            if etag:
                headers["If-Range"] = etag
        try:
            with opener(urllib.request.Request(quoted, headers=headers), timeout=120) as resp:
                if not body or resp.status == 200:  # first request, or the server restarted us
                    body, status = b"", resp.status
                    ctype = resp.headers.get("Content-Type", "")
                    etag = resp.headers.get("ETag")
                    length = resp.headers.get("Content-Length")
                    total = int(length) if length and length.isdigit() else None
                try:
                    body += resp.read()
                except http.client.IncompleteRead as e:
                    body += e.partial
                    last_err = repr(e)
                    sleep(pause)
                    continue
        except urllib.error.HTTPError as e:
            return e.code, None, None, str(e)
        except Exception as e:  # network errors
            return None, None, None, repr(e)
        if total is None or len(body) == total:
            return status, ctype, body, None
        if len(body) > total:
            return None, ctype, None, f"long body: {len(body)} of {total} bytes"
        last_err = f"short body: {len(body)} of {total} bytes"
    return None, ctype, None, f"gave up after {MAX_RESUMES} resumes: {last_err}"


def fetch(url, waits=RETRY_WAITS, sleep=time.sleep, get=_get):
    """Fetch one file. Network errors, short bodies and 5xx are retried after each wait in
    `waits`; 4xx is not. `retries` (state file only, not the shard) counts retries used."""
    rec = {"http_status": None, "content_type": None, "n_bytes": None, "sha256": None,
           "error": None, "content": None, "retries": 0}
    for i in range(len(waits) + 1):
        status, ctype, body, err = get(url)
        transient = status is None or status >= 500
        if not transient or i == len(waits):
            break
        print(f"retrying {url} in {waits[i]}s after: {err or status}", flush=True)
        sleep(waits[i])
        rec["retries"] = i + 1
    rec.update(http_status=status, content_type=ctype, error=err)
    if body is not None and err is None:
        rec.update(n_bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
        if "text/html" in rec["content_type"] or b"Just a moment" in body[:2000]:
            rec.update(http_status=-1, error="looks like an HTML/challenge page")
        else:
            rec["content"] = body
    rec["fetched_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("listing_csv")
    ap.add_argument("state_dir")
    ap.add_argument("repo_id")
    ap.add_argument("--shard-size", type=int, default=1000)
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--limit", type=int, help="stop after this many attempts (for testing)")
    ap.add_argument("--push-state", action="store_true",
                    help=f"commit the state file to {STATE_PATH_IN_REPO} in the same commit as each shard")
    a = ap.parse_args()

    os.makedirs(a.state_dir, exist_ok=True)
    state_path = os.path.join(a.state_dir, "uploaded.jsonl")
    done, n_shards = set(), 0
    if os.path.exists(state_path):
        with open(state_path) as fh:
            for line in fh:
                d = json.loads(line)
                n_shards = max(n_shards, d["shard"] + 1)
                if d["http_status"] == 200:
                    done.add(d["url"])

    first = {}
    with open(a.listing_csv, newline="") as fh:
        for r in csv.DictReader(fh):
            first.setdefault(r["url"], r)
    skipped = [u for u in first if "/sites/default/files/" not in u]
    todo = [u for u in first if "/sites/default/files/" in u and u not in done]
    print(f"unique URLs: {len(first):,}; not file URLs (skipped): {len(skipped)} {skipped}; "
          f"already uploaded: {len(done):,}; to fetch: {len(todo):,}; next shard: {n_shards}", flush=True)

    api = HfApi()
    batch, attempts, bad_streak, stop = [], 0, 0, False

    def flush_batch():
        nonlocal batch, n_shards
        if not batch:
            return
        name = f"data/files-{n_shards:05d}.parquet"
        if api.file_exists(a.repo_id, name, repo_type="dataset"):
            # The state file is behind the repo (e.g. a crash between upload and state write).
            # Never overwrite a shard; stop and reconcile by hand.
            raise RuntimeError(f"{name} already exists on the Hub but not in {state_path}; "
                               "run scripts/reconcile_hf.py before fetching again")
        buf = io.BytesIO()
        pq.write_table(pa.Table.from_pylist(batch, schema=SCHEMA), buf, compression="zstd")
        new_lines = "".join(json.dumps({"shard": n_shards, **{k: v for k, v in r.items() if k != "content"}}) + "\n"
                            for r in batch)
        ops = [CommitOperationAdd(path_in_repo=name, path_or_fileobj=buf.getvalue())]
        if a.push_state:
            old = open(state_path, "rb").read() if os.path.exists(state_path) else b""
            ops.append(CommitOperationAdd(path_in_repo=STATE_PATH_IN_REPO,
                                          path_or_fileobj=old + new_lines.encode()))
        for attempt in range(5):
            try:
                api.create_commit(repo_id=a.repo_id, repo_type="dataset", operations=ops,
                                  commit_message=f"Add {name} ({len(batch)} rows)")
                break
            except Exception as e:
                print(f"upload failed ({attempt + 1}/5): {e!r}", flush=True)
                if attempt == 4:
                    raise
                time.sleep(60 * (attempt + 1))
        with open(state_path, "a") as st:
            st.write(new_lines)
        ok = sum(r["http_status"] == 200 for r in batch)
        print(f"uploaded {name}: {len(batch)} rows, {ok} ok, {buf.tell() / 1e6:.1f} MB "
              f"({datetime.datetime.now().isoformat(timespec='seconds')})", flush=True)
        batch, n_shards = [], n_shards + 1

    for u in todo:
        if a.limit is not None and attempts >= a.limit:
            break
        rec = fetch(u)
        r = first[u]
        batch.append({"url": u, "file_name": r["file_name"], "page": int(r["page"]),
                      "position": int(r["position"]), **rec})
        attempts += 1
        if rec["http_status"] == 200:
            bad_streak = 0
        else:
            bad_streak += 1
            print(f"PROBLEM {u} {rec['http_status']} {rec['error']}", flush=True)
            if rec["http_status"] == -1 or bad_streak >= 5:
                print("STOPPING: challenge page or 5 failures in a row", flush=True)
                stop = True
                break
        if len(batch) >= a.shard_size:
            flush_batch()
        time.sleep(a.delay)
    flush_batch()
    print(f"done this run: {attempts:,} attempts", flush=True)
    return 2 if stop else 0


if __name__ == "__main__":
    sys.exit(main())
