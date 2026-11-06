# EEOC appellate decisions: handoff

## What this is

A copy of every file on EEOC's federal-sector appellate decisions page, kept in a Hugging Face dataset and checked every day for new ones. For decisions posted since 2025, Claude reads each decision and fills in case fields (agency, grounds claimed, outcome).

- Code: https://github.com/abigailhaddad/eeoc-appellate-decisions
- Data: https://huggingface.co/datasets/abigailhaddad/eeoc-appellate-decisions (the card is `hf/README.md`; columns and known limits are there)
- Site: https://eeoc-decisions.abigailhaddad.com, built from https://github.com/abigailhaddad/dataset-explorer

## What runs on its own

- `.github/workflows/update.yml`: the daily job. Finds newly listed files and uploads them, then extracts fields from the new decisions.
- `.github/workflows/recrawl.yml`: the monthly full re-read of the listing, which catches changes the daily job can't see. It runs in chunks and starts its own next chunk.

The schedules are at the top of each file. Both can be started from the Actions tab. `PIPELINE.md` explains how the listing behaves and why the jobs are built this way.

## Secrets

Settings > Secrets and variables > Actions.

- `HF_TOKEN`: write access to the dataset.
- `ANTHROPIC_API_KEY`: pays for the field extraction in the daily job.
- `ANTHROPIC_WORKSPACE_ID` (optional): sent as a header only when set.

## If you take it over

- Find every place that names the current owner: `grep -rn abigailhaddad . --exclude-dir=.git`
- The dataset id is `HF_DATASET` at the top of `update.yml` and `recrawl.yml`. The scripts take it as an argument. The rest are links in `README.md`, `hf/README.md` (the dataset card, which you copy up to the dataset on Hugging Face) and `extraction/README.md`.
- Copy the existing dataset to your account instead of starting empty. `scripts/update.py` downloads `listing.parquet` and `state/uploaded.jsonl` from it first and doesn't create the dataset. I haven't tried an empty start.

## When it breaks

- A failed run opens a GitHub issue ("Daily EEOC update failed" or "Monthly recrawl needs a look") with the end of the log. Run history is in the Actions tab.
- Exit codes are in the docstrings of `scripts/update.py`, `scripts/recrawl.py` and `extraction/update_extracted.py`. Nothing here deletes files from the dataset.
- If eeoc.gov returns a challenge page instead of the listing, the daily job stops (exit code 2).

## Costs

The Claude calls cover new decisions only. A daily run refuses to start if more than 1,500 new decisions are waiting, and stops at $10 of spend (`--max-new` and `--max-usd` in `extraction/update_extracted.py`). How the fields were built and tested: `extraction/README.md`.

## Run it yourself

Commands for the tests and a dry run are in `README.md`.
