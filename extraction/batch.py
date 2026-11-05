"""Run the extraction through the Message Batches API (half price).

usage:
  batch.py submit  <work_dir> [--limit N] [--max-usd 12] [--name full] [--ids FILE]
  batch.py collect <work_dir> [--name full]

submit refuses to run if <work_dir>/batches_<name>.json exists, so a rerun can't pay twice.
collect waits for the batches and writes results_<name>.jsonl, one line per decision.
Needs ANTHROPIC_API_KEY (and ANTHROPIC_WORKSPACE_ID if the key requires it).
"""
import argparse, json, os, sys, time
import anthropic

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prompt import EFFORT, MAX_TOKENS, MODEL, PROMPT, SCHEMA  # noqa: E402

IN_USD, OUT_USD = 0.10 / 1e6 / 2, 0.50 / 1e6 / 2  # batch price: half of list
LONG_IN_USD, LONG_OUT_USD = 0.50 / 1e6 / 2, 2.50 / 1e6 / 2  # prompts over 100K tokens
CHUNK = 2000
EST_OUT = 3400  # measured mean output tokens per decision in the tests
TOOL = {"name": "record_decision", "description": "Record the fields for this decision.", "input_schema": SCHEMA}


def client():
    ws = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    return anthropic.Anthropic(default_headers={"anthropic-workspace-id": ws} if ws else None)


def params(text):
    return {"model": MODEL, "max_tokens": MAX_TOKENS, "tools": [TOOL], "tool_choice": {"type": "auto"},
            "output_config": {"effort": EFFORT}, "messages": [{"role": "user", "content": PROMPT.format(text=text)}]}


def submit(a):
    ledger = f"{a.work_dir}/batches_{a.name}.json"
    if os.path.exists(ledger):
        sys.exit(f"{ledger} exists; not submitting again")
    if a.ids:
        ids = [l.strip() for l in open(a.ids) if l.strip()]
    else:
        ids = sorted(f[:-4] for f in os.listdir(f"{a.work_dir}/text"))
    ids = ids[: a.limit] if a.limit else ids
    reqs, skipped, est = [], [], 0.0
    for s in ids:
        t = open(f"{a.work_dir}/text/{s}.txt").read()
        if len(t.strip()) < 200:
            skipped.append(s)
            continue
        reqs.append({"custom_id": s, "params": params(t)})
        tok = len(t) / 3.0 + 3500
        est += tok * (LONG_IN_USD if tok > 100_000 else IN_USD) + EST_OUT * (LONG_OUT_USD if tok > 100_000 else OUT_USD)
    print(f"{len(reqs)} requests, {len(skipped)} skipped as too short {skipped[:5]}; estimated ${est:.2f}", flush=True)
    if est > a.max_usd:
        sys.exit(f"estimate is over --max-usd {a.max_usd}; nothing submitted")
    c, out = client(), []
    for i in range(0, len(reqs), CHUNK):
        b = c.messages.batches.create(requests=reqs[i:i + CHUNK])
        out.append(b.id)
        with open(ledger, "w") as fh:  # written after each chunk: a crash can't lose a paid batch id
            json.dump({"batches": out, "skipped": skipped}, fh)
        print("created", b.id, len(reqs[i:i + CHUNK]), flush=True)


def collect(a):
    ledger = json.load(open(f"{a.work_dir}/batches_{a.name}.json"))
    c = client()
    while True:
        bs = [c.messages.batches.retrieve(i) for i in ledger["batches"]]
        rc = [b.request_counts for b in bs]
        print(time.strftime("%H:%M"), [b.processing_status for b in bs], "processing", sum(r.processing for r in rc),
              "ok", sum(r.succeeded for r in rc), "errored", sum(r.errored for r in rc), flush=True)
        if all(b.processing_status == "ended" for b in bs):
            break
        time.sleep(120)
    n = usd = 0
    problems = {}
    with open(f"{a.work_dir}/results_{a.name}.jsonl", "w") as fh:
        for i in ledger["batches"]:
            for r in c.messages.batches.results(i):
                rec = {"sha256": r.custom_id, "type": r.result.type, "fields": None}
                if r.result.type == "succeeded":
                    m = r.result.message
                    blk = next((b for b in m.content if b.type == "tool_use"), None)
                    i_, o_ = m.usage.input_tokens, m.usage.output_tokens
                    cost = i_ * (LONG_IN_USD if i_ > 100_000 else IN_USD) + o_ * (LONG_OUT_USD if i_ > 100_000 else OUT_USD)
                    rec.update(stop_reason=m.stop_reason, input_tokens=i_, output_tokens=o_, cost_usd=round(cost, 6),
                               model=m.model, fields=blk.input if blk else None)
                    usd += cost
                if rec["fields"] is None:
                    k = rec.get("stop_reason") or rec["type"]
                    problems[k] = problems.get(k, 0) + 1
                fh.write(json.dumps(rec) + "\n")
                n += 1
    print(f"{n} results, ${usd:.2f}; no fields: {problems}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["submit", "collect"])
    ap.add_argument("work_dir")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--max-usd", type=float, default=12.0)
    ap.add_argument("--name", default="full")
    ap.add_argument("--ids")
    a = ap.parse_args()
    (submit if a.cmd == "submit" else collect)(a)
