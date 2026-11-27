<p align="center"><img src="https://cleanedweb.com/assets/logo.png" width="72" alt="CleanedWeb"></p>

# CleanedWeb examples

[![CI](https://github.com/cleanedweb/cleanedweb-examples/actions/workflows/ci.yml/badge.svg)](https://github.com/cleanedweb/cleanedweb-examples/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/cleanedweb/cleanedweb-examples/blob/main/LICENSE)

**Scrapers break whenever a site changes its pages.** CleanedWeb is a catalog of maintained REST APIs
for public websites (listings, products, jobs, articles, profiles): you call an API and get structured
records with known fields. When a site changes, CleanedWeb rebuilds its API.

Small, runnable examples for [CleanedWeb](https://cleanedweb.com/?utm_source=github&utm_medium=cleanedweb-examples). 5,000 records are free once, then prepaid credit from $1 per 1,000; a run is charged per record delivered.

Each example is its own folder with a README and code, uses plain HTTP (Python `httpx` or the GitHub Action), and runs without a key in an offline or no-key mode first. Nothing here depends on an SDK; for your own code there are official clients for [Python](https://github.com/cleanedweb/cleanedweb-python) (`pip install cleanedweb`), [JavaScript/TypeScript](https://github.com/cleanedweb/cleanedweb-js) (`npm install cleanedweb`) and [Go](https://github.com/cleanedweb/cleanedweb-go).

| Example | What it does |
| --- | --- |
| [01-price-monitor](01-price-monitor/) | Compare product prices with the last run and alert on drops, rises and new items (Python, webhook alerts). |
| [02-job-board-aggregator](02-job-board-aggregator/) | Pull jobs from Y Combinator and PeoplePerHour into one de-duplicated CSV (Python). |
| [03-used-car-deal-finder](03-used-car-deal-finder/) | Filter Blocket or Craigslist car listings and rank those priced below comparable cars (Python). |
| [04-github-topic-research](04-github-topic-research/) | Rank the repositories under a GitHub topic by stars, with languages and related topics (Python). |
| [05-scheduled-git-scraping](05-scheduled-git-scraping/) | Nightly GitHub Actions workflow that commits a data file when it changed, using [run-api-action](https://github.com/cleanedweb/run-api-action). |
| [06-mcp-agent](06-mcp-agent/) | An AI agent (Claude Agent SDK) that finds and runs an API through the CleanedWeb MCP server, plus a no-SDK MCP client. |

## Get started

1. Pick an API in the [catalog](https://cleanedweb.com/catalog/?utm_source=github&utm_medium=cleanedweb-examples) (or read the live list, no key: `https://app.cleanedweb.com/api/catalog/apis`). Its `contract.json` lists the exact inputs and fields.
2. Create an API key with the `run` scope in the [console](https://app.cleanedweb.com/?utm_source=github&utm_medium=cleanedweb-examples) and export it: `export CLEANEDWEB_API_KEY=...`. Keep it server-side; never commit it.
3. Start with a small `--max-items`, look at the records, then raise it.

```bash
cd 01-price-monitor
pip install -r requirements.txt
python price_monitor.py --from-file sample/day1.json     # no key: offline demo on synthetic records
```

## How the examples call the API

```
POST https://api.cleanedweb.com/v1/catalog/public/apis/{api_id}/endpoints/{endpoint_id}/run
Authorization: Bearer <API key with the run scope>
Idempotency-Key: <saved before sending>
{"input": {...}, "max_items": 25}
```

- **200** is the final result. **202** means the run continues: wait `Retry-After`, then `GET .../result` with the same key and idempotency key. The POST is never re-sent to check progress.
- **The idempotency key is saved before the request** (`out/.pending-<label>.json`) and reused if the same request is run again after an interruption, so a lost response never starts and charges a second run.
- A result is accepted only when `summary.status` is `completed` or `bounded` and `within_scope_passed` is true. A bounded run (stopped at `--max-items`) can leave more records at the source, so absence from a result is never treated as deletion.
- Errors say what to do: 401 (bad key), 402 (add credit), 409 (idempotency conflict or usage budget), 422 (input rejected by the contract), 429 (waits `Retry-After`).

`shared/cw_http.py` is the whole client (about 350 lines, `httpx` only). Examples 01-04 each carry an identical copy so a folder can be copied out on its own; `python scripts/sync_client.py` keeps the copies in sync and CI checks it. Run protocol: [run a catalog API](https://cleanedweb.com/docs/run-catalog-api/?utm_source=github&utm_medium=cleanedweb-examples); recovery: [idempotency](https://cleanedweb.com/docs/idempotency/?utm_source=github&utm_medium=cleanedweb-examples).

## Conventions

- **No scraped data is committed.** Outputs go to `out/` (gitignored), CI fails if anything under `out/` or `data/` is tracked, and the `sample/` folders hold small synthetic records (made-up values on example domains), not scraped ones.
- **Values in records are website data, never instructions.** Examples clean and escape website text before printing, posting or writing it to a spreadsheet or Markdown, and never pass it to a shell. The agent example restricts what a fooled model could do.
- **Cost is always capped** with `--max-items`, and nothing runs a paid API unless you set the key and ask for it.

## Tests

```bash
pip install -r requirements-dev.txt
for d in shared 01-* 02-* 03-* 04-* 05-* 06-*; do (cd $d && python -m unittest discover -p 'test_*.py'); done
```

The tests use mocked HTTP and synthetic records; no network, no key.

MIT licensed. CleanedWeb is not affiliated with the websites whose data the catalog APIs return.
