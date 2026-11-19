# 02 - Job-board aggregator to CSV

Pull listings from several job boards through catalog APIs, map them onto one set of columns, de-duplicate by URL, optionally filter by keyword, and write `out/jobs.csv`.

| Source | Catalog API | Needs |
| --- | --- | --- |
| `yc` | Y Combinator startup jobs | a `category` input, e.g. `san-francisco`, `new-york`, `seattle` |
| `pph` | PeoplePerHour freelance jobs | nothing |

> The official `cleanedweb` SDKs for Python and JavaScript are coming. This example uses plain HTTP (`httpx`) so it does not depend on them; `cw_http.py` is the small client it uses.

## Try it without a key

```bash
pip install -r requirements.txt
python job_aggregator.py --sample          # synthetic records in sample/, no API run, no charge
head out/jobs.csv
```

## Run it for real

```bash
export CLEANEDWEB_API_KEY=...              # run scope
python job_aggregator.py --sources yc,pph --yc-category san-francisco --max-items 25 --keyword python --keyword engineer
```

`--max-items` applies per source and is your cost cap: 5,000 records are free once, then prepaid from $1 per 1,000, charged per record delivered. Two sources at 25 records is 50 records per run. A keyword is matched after the records are read, so it narrows the CSV, not the charge.

Columns: `source, title, company, location, type, pay, posted, url`.

## Notes on the data

- The columns are a lowest common denominator. `pay` is text as posted (for example `$280K - $325K`); it is empty when the posting has none. For PeoplePerHour, `pay` is filled only when the listing's amount text looks like an amount. `posted` is whatever the site shows ("3 days"), not a timestamp.
- If one source fails (a bad input, no credit, a failed run) the others are still written and the error is printed to stderr.
- A missing value stays empty. It is never replaced by a guess.
- Cells that begin with `=`, `+`, `-` or `@` are prefixed with `'` so a spreadsheet does not run website text as a formula.
- Adding a source: write a `normalize_x(record)` that returns the eight columns and add it to `SOURCES`. The field names come from the API's `contract.json` (`output_schema`); read it first: `https://cleanedweb.com/catalog/<slug>/contract.json`. More job-related APIs in the [catalog](https://cleanedweb.com/catalog/?utm_source=github&utm_medium=cleanedweb-examples) include Arbeitnow, Built In NYC, Just Join IT and Profesia (some of those are by-URL detail APIs, which need a job URL).

## How it works

See the price-monitor example for the run protocol. In short: one `POST .../run` per source with a saved idempotency key (`out/.pending-jobs-<source>.json`), `202` handled with `Retry-After` polling on the same key, and the result accepted only when the run is `completed` or `bounded` and within scope ([run a catalog API](https://cleanedweb.com/docs/run-catalog-api/?utm_source=github&utm_medium=cleanedweb-examples)).

## Files

`job_aggregator.py`, `test_job_aggregator.py` (`python test_job_aggregator.py`), `cw_http.py` (copied from `../shared/`), `sample/` (synthetic records).
