"""One unreadable PDF must not stop the daily extraction of the other new files."""
import json
import os
import sys

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "extraction"))
import update_extracted as ue  # noqa: E402
from test_extraction import BASE  # noqa: E402


def test_corrupt_pdf_is_reported_and_others_still_extracted(tmp_path, monkeypatch):
    work = tmp_path / "w"
    work.mkdir()
    bad = {"url": "https://x/sites/default/files/decisions/2026_01_02/bad.pdf", "content": b"%PDF-1.4 truncated"}
    good = {"url": "https://x/sites/default/files/decisions/2026_01_02/good.txt", "content": b"Decision text. FOR THE COMMISSION\nJanuary 2, 2026"}
    recs = []
    for sha, r in (("a" * 64, bad), ("b" * 64, good)):
        recs.append({"shard": 0, "url": r["url"], "file_name": r["url"].rsplit("/", 1)[1], "page": 0, "position": 0,
                     "http_status": 200, "n_bytes": len(r["content"]), "sha256": sha})
    shard = pa.Table.from_pylist([{"sha256": "a" * 64, "url": bad["url"], "content": bad["content"]},
                                  {"sha256": "b" * 64, "url": good["url"], "content": good["content"]}])
    pq.write_table(shard, work / "shard.parquet")
    (work / "state.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
    pd.DataFrame({"url": [bad["url"], good["url"]], "numbers": ["", ""], "numbers_loose": ["", ""]}).to_parquet(work / "listing.parquet")
    pd.DataFrame({"sha256": ["z"], "url": ["u"], "numbers": ["1"], "n_urls": [1]}).to_parquet(work / "table.parquet")

    def fake_download(repo, path, **kw):
        return str(work / {"state/uploaded.jsonl": "state.jsonl", "listing.parquet": "listing.parquet",
                           ue.TABLE: "table.parquet"}.get(path, "shard.parquet"))

    monkeypatch.setattr(ue, "download", fake_download)
    monkeypatch.setattr(ue.os, "remove", lambda p: None)
    monkeypatch.setattr(ue, "make_call", lambda: (lambda text: (BASE, 10, 10)))
    monkeypatch.setattr(sys, "argv", ["update_extracted.py", str(work), "o/r", "--no-upload"])
    rc = ue.main()
    out = pd.read_parquet(work / "table_test.parquet")
    assert rc == 1  # one file got no result, retried tomorrow
    assert "b" * 64 in set(out.sha256)
    assert "a" * 64 not in set(out.sha256)
