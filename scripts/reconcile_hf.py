"""Check that the Hub dataset and the state file agree.

Usage:
  python3 -I scripts/reconcile_hf.py <state_dir> <hf_repo_id> [--shards all|new|N,M,...]
                                     [--listing listing.csv]

Checks (exit 1 on any failure):
  - the set of data/files-*.parquet shards on the Hub equals the set of shards in
    uploaded.jsonl, with no gaps in the numbering;
  - for the shards checked (default: the last 2; 'all' reads every shard's url, status and
    sha256 columns, about 15 MB of reads), the rows on the Hub equal the state lines for
    that shard: same count, same (url, http_status, sha256) in the same order;
  - state/uploaded.jsonl on the Hub, if present, is byte-identical to the local one;
  - with --listing: every file URL in the listing has a state line, and the number
    with a 200 plus the number still failing adds up to the number of file URLs.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import defaultdict

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import pyarrow.parquet as pq
from huggingface_hub import HfApi, HfFileSystem

STATE_PATH_IN_REPO = "state/uploaded.jsonl"


def reconcile(state_dir, repo_id, shards="2", listing=None, api=None, fs=None):
    api, fs = api or HfApi(), fs or HfFileSystem()
    failures, notes = [], []
    state_path = os.path.join(state_dir, "uploaded.jsonl")
    raw = open(state_path, "rb").read()
    by_shard = defaultdict(list)
    for line in raw.splitlines():
        d = json.loads(line)
        by_shard[d["shard"]].append(d)

    hub = set()
    for f in api.list_repo_tree(repo_id, repo_type="dataset", path_in_repo="data"):
        m = re.fullmatch(r"data/files-(\d{5})\.parquet", f.path)
        if m:
            hub.add(int(m.group(1)))
    local = set(by_shard)
    if hub != local:
        failures.append(f"shards on Hub but not in state: {sorted(hub - local)[:20]}; "
                        f"in state but not on Hub: {sorted(local - hub)[:20]}")
    if local and sorted(local) != list(range(max(local) + 1)):
        failures.append(f"state shard numbers have gaps: {sorted(set(range(max(local) + 1)) - local)[:20]}")
    notes.append(f"shards: Hub {len(hub)}, state {len(local)}; state lines {sum(map(len, by_shard.values())):,}")

    common = sorted(hub & local)
    if shards == "all":
        check = common
    elif re.fullmatch(r"\d+", shards):
        check = common[-int(shards):]
    else:
        check = [int(s) for s in shards.split(",")]
    for s in check:
        path = f"datasets/{repo_id}/data/files-{s:05d}.parquet"
        with fs.open(path, "rb") as fh:
            t = pq.read_table(fh, columns=["url", "http_status", "sha256"]).to_pylist()
        want = [{"url": d["url"], "http_status": d["http_status"], "sha256": d["sha256"]} for d in by_shard[s]]
        if t != want:
            n_diff = sum(1 for x, y in zip(t, want) if x != y)
            failures.append(f"shard {s}: Hub has {len(t)} rows, state {len(want)}; {n_diff} rows differ")
    notes.append(f"row-checked shards: {len(check)} ({check[0] if check else '-'}..{check[-1] if check else '-'})")

    if api.file_exists(repo_id, STATE_PATH_IN_REPO, repo_type="dataset"):
        with fs.open(f"datasets/{repo_id}/{STATE_PATH_IN_REPO}", "rb") as fh:
            hub_state = fh.read()
        if hashlib.sha256(hub_state).digest() != hashlib.sha256(raw).digest():
            failures.append(f"{STATE_PATH_IN_REPO} on the Hub ({len(hub_state):,} bytes) differs from local ({len(raw):,} bytes)")
        else:
            notes.append(f"{STATE_PATH_IN_REPO} on the Hub matches local")
    else:
        notes.append(f"{STATE_PATH_IN_REPO} not on the Hub yet")

    if listing:
        with open(listing, newline="") as fh:
            urls = {r["url"] for r in csv.DictReader(fh)}
        file_urls = {u for u in urls if "/sites/default/files/" in u}
        latest = {}
        for rows in by_shard.values():
            for d in rows:
                if latest.get(d["url"]) != 200:
                    latest[d["url"]] = d["http_status"]
        missing = file_urls - set(latest)
        ok = sum(1 for u in file_urls if latest.get(u) == 200)
        failing = sorted(u for u in file_urls if u in latest and latest[u] != 200)
        if missing:
            failures.append(f"{len(missing)} listing file URLs have no state line, e.g. {sorted(missing)[:3]}")
        if ok + len(failing) + len(missing) != len(file_urls):
            failures.append("listing arithmetic does not add up")
        notes.append(f"listing: {len(urls):,} unique URLs, {len(file_urls):,} file URLs; "
                     f"{ok:,} fetched OK, {len(failing)} still failing {failing[:5]}, {len(missing)} never tried")
        extra = set(latest) - urls
        if extra:
            notes.append(f"{len(extra)} URLs in state are no longer in the listing, e.g. {sorted(extra)[:3]}")
    return failures, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("state_dir")
    ap.add_argument("repo_id")
    ap.add_argument("--shards", default="2")
    ap.add_argument("--listing")
    a = ap.parse_args()
    failures, notes = reconcile(a.state_dir, a.repo_id, a.shards, a.listing)
    for n in notes:
        print(n)
    for f in failures:
        print("FAIL", f)
    print("OK" if not failures else f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
