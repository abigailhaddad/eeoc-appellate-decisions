"""Tests for scripts/parse_listing.py and scripts/validate_index.py on saved fixture pages.

Fixtures (copied from data/listing_pages): 00000 (2020+ PDFs in dated folders),
02493 (contains a row whose link is the bare site root https://www.eeoc.gov),
06000 (migrated_files .txt decisions).
"""
import csv
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "pages")
PARSE = os.path.join(ROOT, "scripts", "parse_listing.py")
VALIDATE = os.path.join(ROOT, "scripts", "validate_index.py")


def run_parse(pages_dir, out_csv):
    p = subprocess.run([sys.executable, "-I", PARSE, pages_dir, out_csv], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    with open(out_csv, newline="") as fh:
        return list(csv.DictReader(fh)), p.stdout


@pytest.fixture(scope="module")
def parsed(tmp_path_factory):
    out = tmp_path_factory.mktemp("out") / "listing.csv"
    rows, stdout = run_parse(FIX, str(out))
    return rows, stdout, str(out)


def test_ten_rows_per_page(parsed):
    rows, _, _ = parsed
    counts = {}
    for r in rows:
        counts[r["page"]] = counts.get(r["page"], 0) + 1
    assert counts == {"0": 10, "2493": 10, "6000": 10}
    for p in counts:
        assert sorted(int(r["position"]) for r in rows if r["page"] == p) == list(range(10))


def test_dated_folder_row(parsed):
    rows, _, _ = parsed
    r = next(r for r in rows if r["page"] == "0" and r["position"] == "0")
    assert r["url"] == "https://www.eeoc.gov/sites/default/files/decisions/2021_01_19/2020001956.pdf"
    assert r["file_name"] == "2020001956.pdf"
    assert r["folder"] == "decisions/2021_01_19"
    assert r["posted_folder_date"] == "2021-01-19"
    assert r["numbers"] == "2020001956"
    assert r["ext"] == ".pdf"


def test_migrated_row(parsed):
    rows, _, _ = parsed
    r = next(r for r in rows if r["page"] == "6000" and r["position"] == "0")
    assert r["url"] == "https://www.eeoc.gov/sites/default/files/migrated_files/decisions/01A22230.txt"
    assert r["folder"] == "migrated_files/decisions"
    assert r["posted_folder_date"] == ""
    assert r["numbers"] == "01A22230"
    assert r["ext"] == ".txt"


def test_bare_site_link_row_kept_with_no_number(parsed):
    # The source page really lists a link to the site root; the parser must keep the row
    # (so page counts stay at 10) and leave numbers empty.
    rows, _, _ = parsed
    r = next(r for r in rows if r["page"] == "2493" and r["position"] == "1")
    assert r["url"] == "https://www.eeoc.gov"
    assert r["numbers"] == ""
    assert r["folder"] == ""


def test_all_urls_absolute(parsed):
    rows, _, _ = parsed
    assert all(r["url"].startswith("https://www.eeoc.gov") for r in rows)


def test_validate_flags_gaps_and_partial(parsed):
    # Fixture pages are 0, 2493, 6000: a gappy sequence, so validation must fail.
    _, _, out = parsed
    p = subprocess.run([sys.executable, "-I", VALIDATE, out, "--pages-dir", FIX], capture_output=True, text=True)
    assert p.returncode == 1
    assert "missing pages in sequence" in p.stdout


def test_validate_ok_and_zero_byte(tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    shutil.copy(os.path.join(FIX, "00000.html"), pages / "00000.html")
    shutil.copy(os.path.join(FIX, "06000.html"), pages / "00001.html")
    out = str(tmp_path / "listing.csv")
    run_parse(str(pages), out)
    ok = subprocess.run([sys.executable, "-I", VALIDATE, out, "--pages-dir", str(pages), "--last-page", "1"],
                        capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout
    (pages / "00002.html").write_bytes(b"")
    bad = subprocess.run([sys.executable, "-I", VALIDATE, out, "--pages-dir", str(pages)], capture_output=True, text=True)
    assert bad.returncode == 1
    assert "zero-byte page files" in bad.stdout


# File names taken from the real 2026-11 listing; expected values checked against the
# number printed inside each document (except the bundle PDF and truncated name, which
# have no single number in the name to recover).
LOOSE_CASES = [
    ("07-2014-0029-0500.pdf", "0720140029", "hyphenated"),
    ("20-2100-1907.pdf", "2021001907", "hyphenated"),
    ("07-2006-0071_Dennis.txt", "0720060071", "hyphenated"),
    ("20-22001020.pdf", "2022001020", "hyphen20"),
    ("closed0520150131.r.txt", "0520150131", "prefixed"),
    ("posting_order0520160043.txt", "0520160043", "prefixed"),
    ("05200800100520080042.txt", "0520080010;0520080042", "concatenated"),
    ("01-2013-0097-2.txt", "", ""),  # name is wrong: document is Appeal No. 0120151282
    ("01983-2.txt", "", ""),
    ("20200012027.pdf", "", ""),
    ("Redacted OFO Decisions 03-05-2018 through 03-09-2018.pdf", "", ""),
    ("0120051744_r.txt", "", ""),  # strict pattern matches; loose must stay empty
]


def test_loose_numbers(tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    base = "https://www.eeoc.gov/sites/default/files/migrated_files/decisions/"
    items = "".join(
        f'<div class="margin-top-3 views-row"><a href="{base}{n.replace(" ", "%20")}">{n}</a></div>'
        for n, _, _ in LOOSE_CASES)
    (pages / "00000.html").write_text(f"<html><body>{items}</body></html>")
    rows, _ = run_parse(str(pages), str(tmp_path / "listing.csv"))
    got = [(r["file_name"], r["numbers_loose"], r["numbers_loose_rule"]) for r in rows]
    assert got == LOOSE_CASES
    assert rows[-1]["numbers"] == "0120051744"
