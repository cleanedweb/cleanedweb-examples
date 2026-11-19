# 05 - Scheduled git scraping with the run-api-action

Keep a dataset in a git repository, refreshed on a schedule by GitHub Actions. Every night the workflow runs a catalog API, writes the records to a file, and commits the file only if it changed. The git history then shows how the website's data moved, and each run gets a short "what changed" summary.

This uses [`cleanedweb/run-api-action`](https://github.com/cleanedweb/run-api-action) (it handles the `202` + `Retry-After` polling, the idempotency key, and refuses partial or empty results instead of overwriting your file). The example data is the DEV Community feed for one tag.

> The official `cleanedweb` SDKs for Python and JavaScript are coming. This example needs no SDK: the workflow calls the action, and `summarize_diff.py` is standard-library Python.

## Set it up

1. **Create a repository** for the data (private is fine) and add a secret named `CLEANEDWEB_API_KEY`: an API key with the `run` scope from the [console](https://app.cleanedweb.com/?utm_source=github&utm_medium=cleanedweb-examples) (Settings > Secrets and variables > Actions).
2. **Allow the workflow to push**: Settings > Actions > General > Workflow permissions > *Read and write permissions* (the workflow also asks for `contents: write` itself).
3. **Copy two files** into that repository:
   - `nightly-snapshot.yml` to `.github/workflows/nightly-snapshot.yml`
   - `summarize_diff.py` to `scripts/summarize_diff.py`
4. **Run it once by hand**: Actions > *Nightly DEV articles snapshot* > *Run workflow*. It creates `data/dev-mcp-articles.json` and commits it. After the next scheduled run, the job summary lists new and changed records.

Until the action repository is public, other private repositories can use it only if *Settings > Actions > General > Access* on the action repository allows it.

## What the workflow does

```yaml
- uses: cleanedweb/run-api-action@v1
  with:
    api-key: ${{ secrets.CLEANEDWEB_API_KEY }}
    api-id: generated_b634ae9b1a8fb7e781d7c4cf   # DEV Community Articles
    input: '{"t": "# mcp"}'
    max-items: 30
    version: 1
    output-path: data/dev-mcp-articles.json
```

then `git add` + `git diff --staged --quiet || git commit` + `git push`, then `summarize_diff.py` writes Markdown into `$GITHUB_STEP_SUMMARY`.

Choices worth copying:

- `max-items` is your cost cap: a run is charged per record delivered (5,000 free once, then prepaid from $1 per 1,000). 30 records a night is about 900 records a month.
- `version: 1` pins the API's major version so a new major cannot change your data format overnight ([catalog versions](https://cleanedweb.com/docs/catalog-versions/?utm_source=github&utm_medium=cleanedweb-examples)).
- `git add` runs first so a brand-new file counts as a change (a bare `git diff --quiet` ignores untracked files).
- `concurrency` stops two snapshots running at once. Re-running a workflow from the GitHub UI is a new attempt, so it is a new run (and is charged); an interrupted step within one attempt reuses the same idempotency key.
- The commit message carries the record count and run id only, never record text.

## The "what changed" summary

```bash
python scripts/summarize_diff.py data/dev-mcp-articles.json            # HEAD~1 -> HEAD
python scripts/summarize_diff.py data/dev-mcp-articles.json --old HEAD~7 --new HEAD --key url --title title
```

It matches records by `--key` (default `url`) and lists new and changed ones. "No longer in the file" is not "deleted from the website": a bounded run reads only part of the source. Website text is cleaned and Markdown-escaped before it reaches the summary.

## Adapting it

- Another API: change `api-id` and `input` (the contract at `https://cleanedweb.com/catalog/<slug>/contract.json` lists the inputs and fields; reading it needs no key).
- CSV or JSONL instead of JSON: set `format: csv` / `jsonl` and the file extension in `output-path`.
- A different time: edit the `cron` line (UTC). Scheduled workflows run from the default branch.
- Fields that change on every run (counters, "3 days ago") make every night a commit. Choose an API and fields that change when the data really changes, and keep `max-items` small.

Records are website data: never pass them to a shell or an AI agent as instructions, and do not copy them into commit messages or `run:` scripts.

## Files

`nightly-snapshot.yml`, `summarize_diff.py`, `test_summarize_diff.py` (`python test_summarize_diff.py`, which builds a throwaway git history). Action reference: [run-api-action](https://github.com/cleanedweb/run-api-action). More on scheduling: [scheduled runs](https://cleanedweb.com/docs/scheduled-runs/?utm_source=github&utm_medium=cleanedweb-examples).
