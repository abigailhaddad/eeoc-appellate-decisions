"""update.plan() and fetch_pages.fetch() with fakes (no network)."""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import fetch_pages  # noqa: E402
import update  # noqa: E402


def row(page, pos, url):
    return {"page": page, "position": pos, "url": url}


def index_of(urls):
    return pd.DataFrame({"url": urls})


def test_plan_finds_new_and_checks_total():
    idx = index_of(["a", "b", "c"])
    rows = [row(10, 0, "b"), row(10, 1, "a"), row(11, 0, "x"), row(11, 1, "c"), row(12, 0, "y")]
    new, rep = update.plan(idx, rows, total=5)
    assert [r["url"] for r in new] == ["x", "y"]
    assert rep["total_matches"] and rep["index_rows_after"] == 5


def test_plan_reordered_old_rows_are_not_new():
    idx = index_of(["a", "b", "c", "d"])
    rows = [row(10, 0, "d"), row(10, 1, "c"), row(10, 2, "b"), row(10, 3, "a")]
    new, rep = update.plan(idx, rows, total=4)
    assert new == [] and rep["total_matches"]


def test_plan_total_mismatch_when_something_landed_before_window():
    idx = index_of(["a", "b"])
    rows = [row(10, 0, "a"), row(10, 1, "b"), row(11, 0, "x")]
    _, rep = update.plan(idx, rows, total=5)  # site has 2 more rows we never saw
    assert not rep["total_matches"]


def test_plan_flags_new_rows_in_first_pages():
    idx = index_of([str(i) for i in range(100)])
    rows = [row(p, 0, str(p)) for p in range(20)]
    rows[1] = row(1, 0, "new")
    _, rep = update.plan(idx, rows, total=101)
    assert rep["new_in_first_pages"] == 1


def test_plan_repeated_new_url_keeps_both_rows():
    idx = index_of(["a"])
    rows = [row(10, 0, "a"), row(10, 1, "x"), row(11, 0, "x")]
    new, rep = update.plan(idx, rows, total=3)
    assert rep["new_rows"] == 2 and rep["new_urls"] == 1 and rep["total_matches"]


def page_html(first, last, total, n_rows):
    items = "".join(f'<div class="views-row"><a href="/sites/default/files/x{first + i}.pdf">x</a></div>'
                    for i in range(n_rows))
    return f"<html><p>{first} - {last} of {total}</p>{items}</html>".encode()


def fake_site(total, overrides=None):
    overrides = overrides or {}

    def get(url):
        p = int(url.rsplit("=", 1)[1])
        if p in overrides:
            return overrides[p]
        first = p * 10 + 1
        last = min(first + 9, total)
        return 200, page_html(first, last, total, last - first + 1), None
    return get


def test_fetch_last_n(tmp_path):
    meta = fetch_pages.fetch(str(tmp_path), last_n=3, delay=0, get=fake_site(45), sleep=lambda s: None)
    assert meta["last_page"] == 4 and meta["pages"] == [2, 4]
    assert sorted(os.listdir(tmp_path)) == ["00002.html", "00003.html", "00004.html", "fetch_meta.json"]


def test_fetch_stops_if_total_changes_mid_run(tmp_path):
    get = fake_site(45, {3: (200, page_html(31, 40, 46, 10), None)})
    with pytest.raises(fetch_pages.FetchError, match="total changed"):
        fetch_pages.fetch(str(tmp_path), last_n=3, delay=0, get=get, sleep=lambda s: None)


def test_fetch_stops_on_short_page(tmp_path):
    get = fake_site(45, {3: (200, page_html(31, 40, 45, 9), None)})
    with pytest.raises(fetch_pages.FetchError, match="9 rows"):
        fetch_pages.fetch(str(tmp_path), last_n=3, delay=0, get=get, sleep=lambda s: None)


def test_fetch_stops_on_challenge(tmp_path):
    get = fake_site(45, {4: (200, b"<html>Just a moment...</html>", None)})
    with pytest.raises(fetch_pages.FetchError, match="challenge"):
        fetch_pages.fetch(str(tmp_path), last_n=3, delay=0, get=get, sleep=lambda s: None)


def test_fetch_retries_5xx_then_ok(tmp_path):
    calls = {"n": 0}
    base = fake_site(45)

    def get(url):
        if url.endswith("=4") and calls["n"] < 2:
            calls["n"] += 1
            return 503, b"", "503"
        return base(url)
    slept = []
    fetch_pages.fetch(str(tmp_path), last_n=1, delay=0, get=get, sleep=slept.append)
    assert calls["n"] == 2 and 10 in slept and 30 in slept


def test_fetch_404_not_retried(tmp_path):
    get = fake_site(45, {4: (404, b"", "404")})
    with pytest.raises(fetch_pages.FetchError, match="HTTP 404"):
        fetch_pages.fetch(str(tmp_path), last_n=1, delay=0, get=get, sleep=lambda s: None)


class FakeApi:
    def __init__(self, head, blob):
        self.head, self.blob = head, blob

    def repo_info(self, repo_id, repo_type=None):
        return type("I", (), {"sha": self.head})()

    def get_paths_info(self, repo_id, paths, repo_type=None, revision=None):
        assert revision == self.head
        return [type("P", (), {"blob_id": self.blob})()]


def test_guard_head_returns_head_when_listing_unchanged():
    api = FakeApi("h2", "blobA")  # head moved (fetch commits) but listing.parquet did not
    assert update.guard_head(api, "r", "blobA") == "h2"


def test_guard_head_refuses_when_listing_changed():
    api = FakeApi("h2", "blobB")  # a recrawl rewrote listing.parquet
    with pytest.raises(RuntimeError, match="listing.parquet changed"):
        update.guard_head(api, "r", "blobA")
