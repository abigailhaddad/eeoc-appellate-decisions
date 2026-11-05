"""recrawl.py with a fake site (no network, no Hub)."""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import fetch_pages  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
import recrawl  # noqa: E402

U = "https://www.eeoc.gov/sites/default/files/decisions/2026_01_01/{}.pdf"
noop = lambda *a: None


def ago(days):
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()


def site(urls):
    def get(url):
        p = int(url.rsplit("=", 1)[1])
        part = urls[p * 10:p * 10 + 10]
        items = "".join(f'<div class="views-row"><a href="{u}">x</a></div>' for u in part)
        return 200, f"<html><p>{p * 10 + 1} - {p * 10 + len(part)} of {len(urls)}</p>{items}</html>".encode(), None
    return get


def run(urls, known=(), max_pages=1000, state=None, seen=None):
    state, seen = state or recrawl.new_state(), seen if seen is not None else set()
    done = recrawl.crawl(state, set(known), seen, max_pages, 0, noop, get=site(urls), sleep=noop)
    return state, seen, done


def test_decide():
    assert recrawl.decide(None) == "new"
    assert recrawl.decide({"started": ago(2), "finished": None}) == "continue"
    assert recrawl.decide({"started": ago(30), "finished": None}) == "new"
    assert recrawl.decide({"started": ago(5), "finished": ago(4)}) == "skip"
    assert recrawl.decide({"started": ago(40), "finished": ago(39)}) == "new"
    assert recrawl.decide({"started": ago(5), "finished": ago(4)}, force=True) == "new"


def test_crawl_reads_everything_and_finds_new():
    urls = [U.format(i) for i in range(25)]
    state, seen, done = run(urls, known=urls[:24])
    assert done and seen == set(urls) and state["rows_seen"] == 25 and state["next_page"] == 3
    assert [r["url"] for r in state["new_rows"]] == urls[24:]


def test_chunks_continue_where_they_stopped():
    urls = [U.format(i) for i in range(35)]
    state, seen, done = run(urls, max_pages=2)
    assert not done and state["next_page"] == 2 and len(seen) == 20
    state, seen, done = run(urls, max_pages=99, state=state, seen=seen)
    assert done and len(seen) == 35


def test_total_growing_mid_crawl_is_fine():
    urls = [U.format(i) for i in range(20)]
    base = site(urls)
    grown = site(urls + [U.format(99)])
    calls = []

    def get(url):
        calls.append(url)
        return (base if len(calls) < 2 else grown)(url)
    state, seen = recrawl.new_state(), set()
    assert recrawl.crawl(state, set(), seen, 99, 0, noop, get=get, sleep=noop)
    assert U.format(99) in seen and state["first_total"] == 20 and state["last_total"] == 21


def test_bad_page_stops_and_keeps_place():
    urls = [U.format(i) for i in range(30)]
    good = site(urls)

    def get(url):
        return (200, b"<html>Just a moment...</html>", None) if url.endswith("=2") else good(url)
    state, seen = recrawl.new_state(), set()
    with pytest.raises(fetch_pages.FetchError):
        recrawl.crawl(state, set(), seen, 99, 0, noop, get=get, sleep=noop)
    assert state["next_page"] == 2


def test_diff_ignores_non_file_links():
    a, b = U.format(1), U.format(2)
    assert recrawl.diff({a, b, "https://www.eeoc.gov"}, {a}) == [b]


def test_report_counts():
    state = {**recrawl.new_state(), "first_total": 11, "last_total": 12, "rows_seen": 12, "finished": "2026-12-01",
             "new_rows": [{"url": "n"}]}
    r = recrawl.build_report(state, ["a"] * 11, ["m"], {"m": 404})
    assert r["matches_site_total"] and r["new_urls"] == ["n"] and r["missing_and_not_served"] == ["m"]
    r = recrawl.build_report(state, ["a"] * 9, [], {})
    assert not r["matches_site_total"]


class FakeHub:
    upload = False

    def __init__(self, tmp, urls):
        self.work, self.files = str(tmp), {}
        n = len(urls)
        pd.DataFrame({"page": [0] * n, "position": list(range(n)), "url": urls, "file_name": ["f"] * n, "folder": [""] * n,
                      "posted_folder_date": [""] * n, "numbers": [""] * n, "ext": [".pdf"] * n, "numbers_loose": [""] * n,
                      "numbers_loose_rule": [""] * n, "first_seen": ["2026-11-01"] * n}).astype({"page": "int32", "position": "int32"}).to_parquet(f"{tmp}/listing.parquet")

    def get(self, path, required=True):
        return f"{self.work}/listing.parquet" if path == "listing.parquet" else None

    def put(self, files, msg, parent=None):
        self.files.update(files)
        if "listing.parquet" in files:
            open(f"{self.work}/listing.parquet", "wb").write(files["listing.parquet"])


def test_finish_adds_new_reports_missing(tmp_path):
    urls = [U.format(i) for i in range(25)]
    gone = U.format(500)
    hub = FakeHub(tmp_path, urls[:24] + [gone])
    known = set(urls[:24]) | {gone}
    state, seen, done = run(urls, known=known)
    assert done
    code = recrawl.finish(hub, state, known, seen, 0, get=site(urls), sleep=noop, check=lambda u: 404)
    report = json.loads(hub.files[recrawl.REPORT])
    assert code == 3
    assert report["new_urls"] == [urls[24]] and report["missing_from_listing"] == [gone]
    assert report["missing_and_not_served"] == [gone]
    idx = pd.read_parquet(f"{tmp_path}/listing.parquet")
    assert len(idx) == 26 and gone in set(idx.url)  # nothing removed
    assert idx[idx.url == urls[24]].first_seen.iloc[0] == recrawl.today()
    assert json.loads(hub.files[recrawl.STATE])["finished"] == recrawl.today()


def test_finish_clean_exit_and_late_growth(tmp_path):
    urls = [U.format(i) for i in range(30)]
    hub = FakeHub(tmp_path, urls)
    state, seen, done = run(urls, known=set(urls))
    late = urls + [U.format(i) for i in range(30, 33)]  # posted after the crawl read the last page
    code = recrawl.finish(hub, state, set(urls), seen, 0, get=site(late), sleep=noop, check=lambda u: 200)
    assert code == 0 and len(pd.read_parquet(f"{tmp_path}/listing.parquet")) == 33


def test_chunk_stops_at_deadline_and_keeps_place():
    urls = [U.format(i) for i in range(50)]
    ticks = iter(range(100))
    state, seen = recrawl.new_state(), set()
    done = recrawl.crawl(state, set(), seen, 10 ** 6, 0, noop, get=site(urls), sleep=noop, deadline=2, clock=lambda: next(ticks))
    assert not done and state["next_page"] == 2 and len(seen) == 20
