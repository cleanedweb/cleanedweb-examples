# 01 - Price monitor with change alerts

Run a catalog API on a schedule, compare each product's price with the last run, and get told about drops, rises and new items. By default it watches Thomann's ukuleles and accessories (the [Thomann Ukuleles and Accessories listing](https://cleanedweb.com/catalog/thomann-ukuleles-and-accessories-api/?utm_source=github&utm_medium=cleanedweb-examples)), but any API whose records have a stable id (`url`) and a numeric price works.

> The official `cleanedweb` SDKs for Python and JavaScript are coming. This example uses plain HTTP (`httpx`) so it does not depend on them; `cw_http.py` is the small client it uses.

## Try it without a key

The offline demo reads two synthetic days of records from `sample/` (made-up products on example domains). No API run, no charge:

```bash
pip install -r requirements.txt
python price_monitor.py --from-file sample/day1.json   # saves a baseline in out/
python price_monitor.py --from-file sample/day2.json   # prints what changed
```

```
Price drops (1)
  Acme Soprano Uke: 59.00 EUR -> 49.00 EUR (-16.9%)  https://shop.example/p/1
Price rises (1)
  Acme Tenor Uke: 120.00 EUR -> 132.00 EUR (+10.0%)  https://shop.example/p/3
New in this run (1)
  ...
```

## Run it for real

Create an API key with the `run` scope in the [console](https://app.cleanedweb.com/?utm_source=github&utm_medium=cleanedweb-examples), then:

```bash
export CLEANEDWEB_API_KEY=...
python price_monitor.py --max-items 25            # first run: baseline
python price_monitor.py --max-items 25            # later runs: changes since the last run
```

**Cost.** 5,000 records are free once, then prepaid from $1 per 1,000; a run is charged per record delivered. `--max-items` is how you cap it (default 25). A daily 25-record run is about 750 records a month.

Pick another API or input:

```bash
# API id and inputs come from the API's contract.json (no key needed to read it)
python price_monitor.py --api-id generated_ef2595d47b91cc608bbec022 --input '{"manufacturer": "Harley Benton"}' --max-items 50
```

Alerts: set `ALERT_WEBHOOK_URL` (or `--webhook`) to post the report as `{"text": "..."}`, the shape Slack incoming webhooks accept. Schedule it with cron or the [git-scraping example](../05-scheduled-git-scraping/).

## How it works

1. `CleanedWeb().run(...)` sends `POST /v1/catalog/public/apis/{api_id}/endpoints/{endpoint_id}/run` to `https://broker.cleanedweb.com` with the required `Idempotency-Key`, follows a `202` by reading `/result` with the same key after `Retry-After`, and accepts the result only if `summary.status` is `completed` or `bounded` and `within_scope_passed` is true. See [run a catalog API](https://cleanedweb.com/docs/run-catalog-api/?utm_source=github&utm_medium=cleanedweb-examples).
2. The idempotency key is written to `out/.pending-price-monitor.json` **before** the request and reused if you re-run after an interruption, so a lost response never starts and charges a second run.
3. `normalize` keeps records with an id and a price. A missing price is skipped, never treated as 0.
4. `diff_snapshots` compares with `out/prices.json`. Items absent from this run are reported as "not in this run", **not** as removed: a run bounded by `--max-items` sees only part of the source (see [storing results](https://cleanedweb.com/docs/storing-results/?utm_source=github&utm_medium=cleanedweb-examples)).
5. `out/history.csv` appends every observation, so you can chart prices over time. `out/` is gitignored.

Website text (product names) is cleaned and escaped before it goes into a webhook message, because it is data from a website and could contain mentions or markup.

## Files

- `price_monitor.py` - the monitor. `test_price_monitor.py` - unit tests (`python test_price_monitor.py`).
- `cw_http.py` - the HTTP client (copied from `../shared/`). `sample/` - synthetic records for the offline demo.
