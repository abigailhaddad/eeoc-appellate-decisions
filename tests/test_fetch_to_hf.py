"""fetch() retry behaviour, with a fake request function (no network)."""
import hashlib
import http.client
import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "fetch_to_hf", pathlib.Path(__file__).parent.parent / "scripts" / "fetch_to_hf.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

PDF = b"%PDF-1.7 fake"


def fake(responses):
    calls = []

    def get(url):
        calls.append(url)
        return responses[min(len(calls), len(responses)) - 1]
    return get, calls


def run(responses, waits=(1, 2, 3)):
    get, calls = fake(responses)
    slept = []
    return m.fetch("u", waits=waits, sleep=slept.append, get=get), calls, slept


def test_ok_first_try():
    rec, calls, slept = run([(200, "application/pdf", PDF, None)])
    assert rec["http_status"] == 200 and rec["content"] == PDF and rec["retries"] == 0
    assert rec["sha256"] == hashlib.sha256(PDF).hexdigest() and len(calls) == 1 and slept == []


def test_incomplete_read_then_ok():
    rec, calls, slept = run([(None, None, None, "IncompleteRead(70744 bytes read, 34803 more expected)"),
                             (200, "application/pdf", PDF, None)])
    assert rec["http_status"] == 200 and rec["content"] == PDF and rec["error"] is None
    assert rec["retries"] == 1 and slept == [1] and len(calls) == 2


def test_short_body_and_5xx_retried_until_exhausted():
    rec, calls, slept = run([(None, "application/pdf", None, "short body: 5 of 9 bytes"), (503, None, None, "503")])
    assert len(calls) == 4 and slept == [1, 2, 3] and rec["retries"] == 3
    assert rec["http_status"] == 503 and rec["content"] is None


def test_404_not_retried():
    rec, calls, slept = run([(404, None, None, "HTTP Error 404: Not Found")])
    assert rec["http_status"] == 404 and len(calls) == 1 and slept == [] and rec["content"] is None


def test_challenge_page_flagged_not_retried():
    rec, calls, _ = run([(200, "text/html; charset=UTF-8", b"<html>Just a moment...</html>", None)])
    assert rec["http_status"] == -1 and rec["content"] is None and len(calls) == 1


def test_empty_200_kept():
    rec, *_ = run([(200, "", b"", None)])
    assert rec["http_status"] == 200 and rec["n_bytes"] == 0 and rec["content"] == b""


class Resp:
    """Fake urlopen response: serves `data`, or raises IncompleteRead after `cut` bytes."""

    def __init__(self, status, data, length, cut=None, etag='"e1"'):
        self.status, self.data, self.cut = status, data, cut
        self.headers = {"Content-Type": "application/pdf", "Content-Length": str(length), "ETag": etag}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        if self.cut is not None:
            raise http.client.IncompleteRead(self.data[:self.cut], len(self.data) - self.cut)
        return self.data


def server(data, cuts):
    """urlopen stand-in honouring Range; the nth request is cut after cuts[n] bytes."""
    seen = []

    def opener(req, timeout=None):
        rng = req.get_header("Range")
        seen.append((rng, req.get_header("If-range")))
        start = int(rng.split("=")[1].rstrip("-")) if rng else 0
        cut = cuts[len(seen) - 1] if len(seen) <= len(cuts) else None
        rest = data[start:]
        return Resp(206 if rng else 200, rest, len(rest), cut)
    return opener, seen


def test_get_resumes_after_drops():
    data = bytes(range(256)) * 40
    opener, seen = server(data, [1000, 2000])
    status, ctype, body, err = m._get("http://x/a.pdf", opener=opener, sleep=lambda s: None)
    assert (status, err) == (200, None) and body == data
    assert [s[0] for s in seen] == [None, "bytes=1000-", "bytes=3000-"]
    assert seen[1][1] == '"e1"'


def test_get_restarts_if_server_ignores_range():
    data = b"abcdefghij"
    calls = []

    def opener(req, timeout=None):
        calls.append(req.get_header("Range"))
        return Resp(200, data, len(data), cut=4 if len(calls) == 1 else None)
    status, _, body, err = m._get("http://x/a.pdf", opener=opener, sleep=lambda s: None)
    assert body == data and err is None and calls == [None, "bytes=4-"]


def test_get_gives_up_without_body():
    data = b"x" * 100

    def opener(req, timeout=None):
        return Resp(206 if req.get_header("Range") else 200, data, 100, cut=0)
    status, _, body, err = m._get("http://x/a.pdf", opener=opener, sleep=lambda s: None)
    assert status is None and body is None and "gave up" in err


def test_get_short_body_without_exception_is_not_success():
    def opener(req, timeout=None):
        r = Resp(206 if req.get_header("Range") else 200, b"", 0)
        r.headers["Content-Length"] = "10"
        r.data = b"abc" if not req.get_header("Range") else b""
        return r
    status, _, body, err = m._get("http://x/a.pdf", opener=opener, sleep=lambda s: None)
    assert status is None and body is None and "short body" in err
