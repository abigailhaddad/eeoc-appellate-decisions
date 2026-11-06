"""Daily: extract fields for files that aren't in the published table yet.

usage: update_extracted.py <work_dir> <hf_repo_id> [--max-new N] [--max-usd X] [--no-upload] [--drop-rows N]

Reads state/uploaded.jsonl, listing.parquet and the table from the Hub. Files in folders dated 2025 or later
with no row are read from their shards (OCR where needed), sent through the tested prompt, checked by
build_table.build_row, and appended. The table is uploaded after each chunk, so a crash loses little.
--no-upload writes locally only. --drop-rows N removes N rows first, to test the path end to end.

Exit codes: 0 ok; 1 some files still have no row (the next run retries them); 2 stopped by a limit.
"""
import argparse, io, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import anthropic
import pandas as pd
import pyarrow.parquet as pq
from huggingface_hub import CommitOperationAdd, HfApi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from batch import params  # noqa: E402
from build_table import POSTED_RE, build_row, fill_blank_numbers, number_map, schema_errors  # noqa: E402
from text import download, to_text  # noqa: E402

TABLE = "extracted/decisions.parquet"
FIRST_YEAR = 2025
IN_USD, OUT_USD = 0.10 / 1e6, 0.50 / 1e6
LONG_IN_USD, LONG_OUT_USD = 0.50 / 1e6, 2.50 / 1e6
CHUNK = 100
WORKERS = 4
ATTEMPTS = 2


def eligible(records):
    """Fetched, non-empty files in folders dated FIRST_YEAR or later, grouped by hash."""
    by = {}
    for r in records:
        m = POSTED_RE.search(r["url"])
        if m and int(m.group(1)) >= FIRST_YEAR and r["http_status"] == 200 and r["n_bytes"]:
            by.setdefault(r["sha256"], []).append(r)
    return by


def extract_one(text, call, attempts=ATTEMPTS):
    """(fields or None, cost). call(text) -> (fields, input_tokens, output_tokens). Retries a missing or
    malformed result; API errors propagate so the run stops instead of burning through every file."""
    cost = 0.0
    for _ in range(attempts):
        f, i, o = call(text)
        cost += i * (LONG_IN_USD if i > 100_000 else IN_USD) + o * (LONG_OUT_USD if i > 100_000 else OUT_USD)
        if f is not None and not schema_errors(f):
            return f, cost
    return None, cost


def make_call():
    ws = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    c = anthropic.Anthropic(max_retries=4, timeout=300, default_headers={"anthropic-workspace-id": ws} if ws else None)

    def call(text):
        m = c.messages.create(**params(text))
        blk = next((b for b in m.content if b.type == "tool_use"), None)
        return (blk.input if blk else None), m.usage.input_tokens, m.usage.output_tokens
    return call


def merge(table, new_rows, by_sha):
    out = pd.concat([table, pd.DataFrame(new_rows)], ignore_index=True) if new_rows else table.copy()
    out["n_urls"] = [len(by_sha.get(s, [])) or n for s, n in zip(out.sha256, out.n_urls)]
    return out


def upload(api, repo, df, msg):
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    for attempt in range(5):
        try:
            api.create_commit(repo_id=repo, repo_type="dataset", commit_message=msg,
                              operations=[CommitOperationAdd(path_in_repo=TABLE, path_or_fileobj=buf.getvalue())])
            return
        except Exception as e:
            print(f"upload failed ({attempt + 1}/5): {str(e)[:120]}", flush=True)
            if attempt == 4:
                raise
            time.sleep(60 * (attempt + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir")
    ap.add_argument("repo_id")
    ap.add_argument("--max-new", type=int, default=1500)
    ap.add_argument("--max-usd", type=float, default=10.0)
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--drop-rows", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(a.work_dir, exist_ok=True)
    get = lambda p: download(a.repo_id, p, repo_type="dataset", local_dir=a.work_dir, force_download=True)
    records = [json.loads(l) for l in open(get("state/uploaded.jsonl"))]
    nums = number_map(pd.read_parquet(get("listing.parquet")))
    table = pd.read_parquet(get(TABLE))
    # Rows built from an older listing, or from a hyphenated file name, can have a blank number. Fill them
    # from the current listing now. This costs nothing and calls no model.
    table, filled = fill_blank_numbers(table, nums)
    if filled:
        print(f"filled {filled} blank appeal numbers from the listing", flush=True)
        if not a.no_upload:
            upload(HfApi(), a.repo_id, table, f"Fill {filled} blank appeal numbers from the listing")
    if a.drop_rows:
        table = table.sample(frac=1, random_state=1).iloc[a.drop_rows:].sort_index().reset_index(drop=True)
    by_sha = eligible(records)
    todo = [s for s in by_sha if s not in set(table.sha256)]
    print(f"eligible files {len(by_sha)}, in table {len(table)}, to extract {len(todo)}", flush=True)
    if len(todo) > a.max_new:
        print(f"STOPPING: {len(todo)} files is more than --max-new {a.max_new}; check by hand", flush=True)
        return 2
    api, call, spent, stopped, done, failed = HfApi(), make_call(), 0.0, False, 0, []
    shards = {}
    for s in todo:
        shards.setdefault(by_sha[s][0]["shard"], []).append(s)
    for shard, shas in sorted(shards.items()):
        f = download(a.repo_id, f"data/files-{shard:05d}.parquet", repo_type="dataset", local_dir=a.work_dir)
        want = set(shas)
        got = {r["sha256"]: r for r in pq.read_table(f, columns=["sha256", "url", "content"]).to_pylist()
               if r["sha256"] in want and r["content"]}
        os.remove(f)
        for i in range(0, len(shas), CHUNK):
            part = [s for s in shas[i:i + CHUNK] if s in got]
            failed += [s for s in shas[i:i + CHUNK] if s not in got]
            texts = {}
            for s in part:
                t, _, ocr = to_text(got[s]["content"], got[s]["url"].lower().endswith(".pdf"))
                texts[s] = (t, ocr > 0)
            with ThreadPoolExecutor(WORKERS) as ex:
                results = list(ex.map(lambda s: extract_one(texts[s][0], call), part))
            rows = []
            for s, (fields, cost) in zip(part, results):
                spent += cost
                if fields is None:
                    failed.append(s)
                    continue
                rows.append(build_row(s, by_sha[s], fields, texts[s][0], nums, texts[s][1]))
            table = merge(table, rows, by_sha)
            done += len(rows)
            print(f"shard {shard}: +{len(rows)} rows, spent ${spent:.2f}", flush=True)
            if a.no_upload:
                table.to_parquet(f"{a.work_dir}/table_test.parquet", index=False)
            elif rows:
                upload(api, a.repo_id, table, f"Add extracted fields for {len(rows)} files")
            if spent >= a.max_usd:
                print(f"STOPPING: spent ${spent:.2f}, limit {a.max_usd}", flush=True)
                stopped = True
                break
        if stopped:
            break
    print(f"added {done}, no result {len(failed)} {[s[:10] for s in failed[:5]]}, spent ${spent:.2f}, table {len(table)}", flush=True)
    return 2 if stopped else (1 if failed else 0)


if __name__ == "__main__":
    sys.exit(main())
