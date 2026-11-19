# 03 - Used-car deal finder

Read used-car listings, apply your filters, and rank the cars priced well below comparable listings.

| `--source` | Catalog API | Currency |
| --- | --- | --- |
| `blocket` (default) | Blocket vehicle listings, Sweden | SEK |
| `craigslist` | Craigslist cars & trucks, SF Bay Area | USD |

> The official `cleanedweb` SDKs for Python and JavaScript are coming. This example uses plain HTTP (`httpx`) so it does not depend on them; `cw_http.py` is the small client it uses.

## Try it without a key

```bash
pip install -r requirements.txt
python deal_finder.py --list-makes        # live read of the Blocket contract.json: no key, free
python deal_finder.py --sample            # synthetic Blocket records, no API run
python deal_finder.py --sample --source craigslist
```

`--list-makes` shows how the example turns `--make Volvo` into the API's own input: Blocket's `variant` input is a menu whose labels and codes are published in `contract.json`, so `Volvo` becomes `"variant": "0.818"`.

## Run it for real

```bash
export CLEANEDWEB_API_KEY=...
python deal_finder.py --source blocket --make Volvo --min-year 2016 --max-price 200000 --max-mileage 150000 --fuel diesel --max-items 100
python deal_finder.py --source craigslist --keyword toyota --max-price 15000 --max-items 100
```

Cost: charged per record delivered (5,000 free once, then prepaid from $1 per 1,000); `--max-items` caps it (default 100).

Filters:

- Sent to the API (so you pay only for matching records): Blocket `--make`, `--min-year` (`year_from`), `--max-price` (`price_to`), sorted cheapest first; Craigslist `--min-year`, `--max-price` and the first `--keyword` (`auto_make_model`).
- Applied to the records you read: `--max-mileage`, `--fuel`, `--transmission`, all `--keyword`s. A listing with no value for a filtered field is dropped, never assumed to match.

## What "deal" means

A car is a deal when its price is at least `--min-discount` percent (default 10) below the **median price of comparable listings in the same run**: the same make and model, model year within 3 years, at least 3 comparables including itself. Cars with fewer than 3 comparables get no verdict. This is a screening aid over one bounded sample of one website, not a valuation: read the listing, check the history and inspect the car.

Output: a table on screen and `out/deals.csv` (gitignored).

## Things worth knowing

- **Mileage units.** Craigslist odometers are miles. Blocket's `mileage` is converted from Swedish "mil" (10 km) to km only when the record's `mileage_unit` says "mil"; otherwise the value is taken as km. Check a few records against the listing before trusting a mileage filter, and note `--max-mileage` is in km for Blocket and miles for Craigslist.
- **Menus can drift.** The contract marks most Blocket menu values `observed` and only a few `verified`; a value the site no longer offers is refused with a `422`, never silently ignored.
- **Coverage.** The Blocket listing's own limitations say the saved sample covers one make; read the `limitations` of any API before relying on it ([catalog APIs](https://cleanedweb.com/docs/catalog-apis/?utm_source=github&utm_medium=cleanedweb-examples)).
- Listing text is data from a website; cells starting with `=`, `+`, `-` or `@` are prefixed with `'` in the CSV.

## Files

`deal_finder.py`, `test_deal_finder.py` (`python test_deal_finder.py`), `cw_http.py` (copied from `../shared/`), `sample/` (synthetic records, made-up URLs).
