# eeoc-appellate-decisions

Downloads every file on EEOC's [federal-sector appellate decisions](https://www.eeoc.gov/federal-sector/appellate-decisions)
listing into the Hugging Face dataset
[`abigailhaddad/eeoc-appellate-decisions`](https://huggingface.co/datasets/abigailhaddad/eeoc-appellate-decisions),
and checks daily for new ones (`.github/workflows/update.yml`), with a full recrawl monthly
(`.github/workflows/recrawl.yml`).

What's in the data: `hf/README.md` (the dataset card). How the listing behaves and how
updates work: `PIPELINE.md`. Taking over the repo: `HANDOFF.md`. Each script's docstring and `--help` give its options and
defaults.

## Scripts

- `update.py`: the daily job. Fetches the end of the listing, finds new URLs, downloads
  them to the Hub, and reconciles.
- `recrawl.py`: the monthly job. Reads the whole listing in chunks and reports new and missing files.
- `fetch_pages.py`: fetches listing pages.
- `parse_listing.py`: turns saved listing pages into one row per listed file.
- `validate_index.py`: checks a full crawl.
- `fetch_to_hf.py`: downloads files and uploads them to the Hub in Parquet shards.
- `reconcile_hf.py`: checks the Hub against the state file.
- `fetch_files.py`: older downloader to local disk.

`extraction/` reads fields out of decisions posted since 2025 with Claude; its README says which fields and how
they were tested.

## Running

```sh
uv run --no-project --with pytest --with lxml --with pandas --with pyarrow --with huggingface_hub --with anthropic \
  python -I -m pytest -q tests

# reads the Hub and the live site, uploads nothing
uv run --no-project --with lxml --with pandas --with pyarrow --with huggingface_hub \
  python -I scripts/update.py work abigailhaddad/eeoc-appellate-decisions --dry-run
```

A real run needs `HF_TOKEN` with write access to the dataset, and extraction needs `ANTHROPIC_API_KEY` (repo
secrets in Actions).
The exit codes are in `update.py`'s docstring.

Code: MIT. The decisions are U.S. government records.
