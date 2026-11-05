# EEOC appellate decisions: operator guide

For whoever runs this next. You don't need to be a developer for the routine parts.

## What it does

EEOC posts its federal-sector appellate decisions as a long web listing of files (.txt, .pdf, .docx). This
repo copies every listed file into a Hugging Face dataset, and each day it:

1. Looks at the end of the listing for newly posted files and uploads them.
2. Asks Claude to read each new decision and fill in a handful of fields (agency, bases of discrimination,
   whether discrimination was found, and so on).

Once a month it re-reads the whole listing to catch anything the daily job can't see, such as a file listed
early in the list or a removal.

You don't run anything by hand. When something breaks, the workflow opens a GitHub issue.

## Where things live

| What | Where |
|---|---|
| The data | https://huggingface.co/datasets/abigailhaddad/eeoc-appellate-decisions (card: `hf/README.md`) |
| The code | This repo |
| Daily job | `.github/workflows/update.yml`, 11:17 UTC every day |
| Monthly recrawl | `.github/workflows/recrawl.yml`, starts on days 1 to 4 of the month at 03:17 UTC |
| How updates work, and why | `PIPELINE.md` |
| How the Claude-extracted fields were built and tested | `extraction/README.md` |
| Run history | The Actions tab |
| Failures | The Issues tab |

The recrawl takes longer than one job may run, so each run does a chunk, saves its place on the Hugging Face
dataset (`state/recrawl.json`), and starts the next one. The later dates in the schedule only pick up a crawl
that stalled. If nothing is under way, they do nothing.

## Secrets

Set these under Settings > Secrets and variables > Actions.

| Secret | What it's for | Used by |
|---|---|---|
| `HF_TOKEN` | A Hugging Face token with write access to the dataset | Daily update, field extraction, monthly recrawl |
| `ANTHROPIC_API_KEY` | Pays for the Claude calls that extract fields from new decisions | Field extraction in the daily job |
| `ANTHROPIC_WORKSPACE_ID` | Sent as the `anthropic-workspace-id` header. The code only sends it if it's set, so you can leave it out if your key doesn't need it | Field extraction in the daily job |

The recrawl only needs `HF_TOKEN`. The daily job also uses GitHub's built-in token to open issues, so you
set nothing for that.

## Moving it to a new owner

Everything that names the current owner:

1. **`.github/workflows/update.yml` and `.github/workflows/recrawl.yml`**: change `HF_DATASET` at the top of
   each file. This is the only place the scripts get the dataset id from.
2. **The dataset itself**: it has to exist on the new account (or be transferred) before the first run. The
   daily job downloads `listing.parquet` and `state/uploaded.jsonl` from it at the start of every run. I haven't
   tried starting from an empty dataset, so this guide doesn't cover that.
3. **Text that mentions the old name** (links and examples, not behavior):
   - `README.md`: the dataset link and the `--dry-run` example
   - `hf/README.md`: three GitHub links and the "Code:" line. This is the dataset card, so it needs to be
     copied up to the dataset's own README on Hugging Face for the change to show.
   - `extraction/README.md`: the example command
4. **The three secrets above**, with the new owner's values.

## When something breaks

The daily job opens an issue titled "Daily EEOC update failed (date)" with the last 40 lines of the log. The
recrawl opens "Monthly recrawl needs a look (date)". The exit code tells you what happened:

| Exit code | Daily job | Recrawl |
|---|---|---|
| 1 | The check of the Hub against its state file failed. From the extraction step: some files got no result and will be retried tomorrow. | |
| 2 | Stopped before finishing: a fetch error, a challenge page from eeoc.gov, more than 3,000 new rows, or a window that couldn't reach the frontier. From the extraction step: stopped by a limit. | Stopped on an error. Progress is kept; run it again to continue. |
| 3 | Finished, but the index and the site's total disagree. Start the monthly recrawl by hand with the `force` input. | Finished, with URLs in the index that aren't in the listing. See `state/recrawl_report.json` on the Hub. |

`PIPELINE.md` has the detail on each stop. Nothing is deleted from the dataset by any of these jobs. Missing
URLs are reported, not removed.

## Running it yourself

Tests:

```sh
uv run --no-project --with pytest --with lxml --with pandas --with pyarrow --with huggingface_hub --with anthropic \
  python -I -m pytest -q tests
```

A dry run reads the Hub and the live site and uploads nothing:

```sh
uv run --no-project --with lxml --with pandas --with pyarrow --with huggingface_hub \
  python -I scripts/update.py work YOUR_ACCOUNT/YOUR_DATASET --dry-run
```
