"""Text for every decision posted in 2025-26, from the Hub shards. Pages with under 100 characters
(except the last) are OCRed: EEOC often flattens page 1 to an image to redact the name.

usage: build_text.py <work_dir> <hf_repo_id>
Writes <work_dir>/text/<sha256>.txt and <work_dir>/files.jsonl. Rerunning skips finished files.
"""
import json, os, re, subprocess, sys, tempfile, time
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

work, repo = sys.argv[1], sys.argv[2]


def download(*args, **kw):
    """Hub downloads share a quota of 5,000 requests per 5 minutes across the account."""
    for attempt in range(8):
        try:
            return hf_hub_download(*args, **kw)
        except Exception as e:
            print(f"download failed ({attempt + 1}/8), waiting 2 min: {str(e)[:120]}", flush=True)
            time.sleep(120)
    raise RuntimeError("Hub download kept failing")


os.makedirs(f"{work}/text", exist_ok=True)
state = download(repo, "state/uploaded.jsonl", repo_type="dataset", local_dir=work, force_download=True)
pat = re.compile(r"/(202[56])[-_](\d\d)[-_/]")
rows = [r for r in map(json.loads, open(state)) if pat.search(r["url"]) and r["http_status"] == 200 and r["n_bytes"]]
with open(f"{work}/files.jsonl", "w") as fh:
    for r in rows:
        fh.write(json.dumps({k: r[k] for k in ("url", "file_name", "sha256", "n_bytes", "shard")}) + "\n")
first = {}
for r in rows:
    first.setdefault(r["sha256"], r)
todo = {s: r for s, r in first.items() if not os.path.exists(f"{work}/text/{s}.txt")}
print(f"files {len(rows)}, unique {len(first)}, to do {len(todo)}", flush=True)


def to_text(raw, is_pdf):
    if not is_pdf:
        return raw.decode("utf-8", "replace"), 0, 0
    ocr = 0
    with tempfile.TemporaryDirectory() as d:
        p = f"{d}/f.pdf"
        open(p, "wb").write(raw)
        info = subprocess.run(["pdfinfo", p], capture_output=True, text=True).stdout
        n = int(re.search(r"Pages:\s+(\d+)", info).group(1))
        t = subprocess.run(["pdftotext", p, "-"], capture_output=True, text=True, errors="replace").stdout.split("\f")[:n]
        for i, x in enumerate(t):
            if len(x.strip()) < 100 and i < n - 1:
                subprocess.run(["pdftoppm", "-f", str(i + 1), "-l", str(i + 1), "-r", "200", "-png", "-singlefile", p, f"{d}/p"], check=True)
                subprocess.run(["tesseract", f"{d}/p.png", f"{d}/p"], capture_output=True, check=True)
                t[i] = open(f"{d}/p.txt").read()
                ocr += 1
    return "\f".join(t), n, ocr


log = open(f"{work}/text_log.jsonl", "a")
for shard in sorted({r["shard"] for r in todo.values()}):
    f = download(repo, f"data/files-{shard:05d}.parquet", repo_type="dataset", local_dir=f"{work}/shards")
    done = 0
    for r in pq.read_table(f, columns=["sha256", "url", "content"]).to_pylist():
        s = r["sha256"]
        if s in todo and r["content"] and not os.path.exists(f"{work}/text/{s}.txt"):
            try:
                text, n, ocr = to_text(r["content"], r["url"].lower().endswith(".pdf"))
            except Exception as e:
                log.write(json.dumps({"sha256": s, "error": repr(e)}) + "\n"); log.flush()
                continue
            open(f"{work}/text/{s}.txt", "w").write(text)
            log.write(json.dumps({"sha256": s, "pages": n, "ocr_pages": ocr, "chars": len(text)}) + "\n"); log.flush()
            done += 1
    os.remove(f)
    print(f"shard {shard}: {done} files", flush=True)
print("done", len(os.listdir(f"{work}/text")), flush=True)
