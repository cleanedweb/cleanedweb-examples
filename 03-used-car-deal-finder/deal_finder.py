#!/usr/bin/env python3
"""Used-car deal finder: filter listings and rank the ones priced well below comparable cars.

Sources (published catalog APIs; a run is charged per record delivered):
  blocket      Blocket.se vehicle listings (Sweden, SEK)
  craigslist   Craigslist cars & trucks, SF Bay Area (USD)

    python deal_finder.py --list-makes               # reads the Blocket contract.json: no key, free
    export CLEANEDWEB_API_KEY=...
    python deal_finder.py --source blocket --make Volvo --min-year 2016 --max-price 200000 --max-items 100
    python deal_finder.py --source craigslist --keyword toyota --max-price 15000 --max-items 100

    python deal_finder.py --sample                   # offline demo on synthetic records, no key, no charge

A "deal" is a car priced at least --min-discount percent below the median price of comparable listings in
the same run (same make and model, model year within 3 years, at least 3 comparables). It is a screening
aid on a bounded sample of one website, not a valuation.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

from cw_http import CleanedWeb, CleanedWebError, clean_text, input_values

BLOCKET = {"slug": "blocket-vehicle-listings-api", "api_id": "generated_c339677c254f69a380ef3a54"}
CRAIGSLIST = {"slug": "craigslist-cars-trucks-sf-bay-area-api", "api_id": "generated_6003a8cf27962b04abcf6b66"}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    digits = re.sub(r"[^\d.]", "", str(value).replace(",", ""))
    try:
        return float(digits)
    except ValueError:
        return None


def normalize_blocket(r: dict) -> dict:
    unit = str(r.get("mileage_unit") or "").lower()
    mileage = _num(r.get("mileage"))
    # Swedish "mil" is 10 km. Convert only when the record says so; otherwise the value is taken as km.
    if mileage is not None and unit.startswith("mil") and not unit.startswith("mile"):
        mileage *= 10
    make = r.get("brand") or r.get("make") or ""
    return {
        "title": r.get("title"), "price": _num(r.get("price")), "currency": r.get("currency") or "SEK",
        "year": _num(r.get("year")), "mileage": mileage, "unit": "km", "fuel": r.get("fuel"),
        "transmission": r.get("transmission"), "group": f"{make} {r.get('model') or ''}".strip().lower(),
        "location": r.get("location"), "url": r.get("url"),
    }


def normalize_craigslist(r: dict) -> dict:
    year = _num(r.get("vehicle_year"))
    name = re.sub(r"\s+", " ", str(r.get("vehicle_name") or r.get("title") or "")).strip().lower()
    group = re.sub(r"^\d{4}\s+", "", name)  # "1998 toyota tacoma" -> "toyota tacoma"
    return {
        "title": r.get("title"), "price": _num(r.get("price")), "currency": r.get("currency") or "USD",
        "year": year, "mileage": _num(r.get("odometer")), "unit": "mi", "fuel": r.get("fuel"),
        "transmission": r.get("transmission"), "group": group, "location": r.get("location") or r.get("address_locality"),
        "url": r.get("url"),
    }


SOURCES = {"blocket": (BLOCKET, normalize_blocket), "craigslist": (CRAIGSLIST, normalize_craigslist)}


def passes(car: dict, f: argparse.Namespace) -> bool:
    """Client-side filters. A car with no value for a filtered field is dropped, never assumed to pass."""
    if car["price"] is None or car["price"] <= 0 or not car["url"]:
        return False
    if f.min_year and (car["year"] is None or car["year"] < f.min_year):
        return False
    if f.max_price and car["price"] > f.max_price:
        return False
    if f.max_mileage and (car["mileage"] is None or car["mileage"] > f.max_mileage):
        return False
    if f.fuel and f.fuel.lower() not in str(car["fuel"] or "").lower():
        return False
    if f.transmission and f.transmission.lower() not in str(car["transmission"] or "").lower():
        return False
    if f.keyword and not all(k.lower() in f"{car['title']} {car['group']}".lower() for k in f.keyword):
        return False
    return True


def score_deals(cars: list[dict], min_comparables: int = 3, year_window: int = 3) -> list[dict]:
    """Add `median` and `discount` (percent below the median of comparable cars) to each car that has comparables."""
    out = []
    for car in cars:
        peers = [
            c["price"] for c in cars
            if c is not car and c["group"] == car["group"] and c["group"]
            and (car["year"] is None or c["year"] is None or abs(c["year"] - car["year"]) <= year_window)
        ]
        if len(peers) + 1 >= min_comparables:
            median = statistics.median(peers + [car["price"]])
            out.append({**car, "median": median, "discount": (median - car["price"]) / median * 100, "comparables": len(peers) + 1})
        else:
            out.append({**car, "median": None, "discount": None, "comparables": len(peers) + 1})
    return out


def rank(cars: list[dict], min_discount: float) -> list[dict]:
    scored = [c for c in score_deals(cars) if c["discount"] is not None and c["discount"] >= min_discount]
    return sorted(scored, key=lambda c: -c["discount"])


def print_table(rows: list[dict], limit: int = 20) -> None:
    print(f"{'off%':>5}  {'price':>9}  {'year':>4}  {'mileage':>10}  {'cmp':>3}  car")
    for c in rows[:limit]:
        mileage = f"{c['mileage']:,.0f} {c['unit']}" if c["mileage"] is not None else "-"
        year = f"{c['year']:.0f}" if c["year"] else "-"
        print(f"{c['discount']:>5.0f}  {c['price']:>9,.0f}  {year:>4}  {mileage:>10}  {c['comparables']:>3}  {clean_text(c['title'], 50)}  {c['url']}")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["discount", "price", "currency", "median", "comparables", "year", "mileage", "unit", "fuel", "transmission", "group", "location", "title", "url"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            # website text that begins with = + - @ would be run as a formula by a spreadsheet
            writer.writerow({k: ("'" + str(v) if isinstance(v, str) and v[:1] in "=+-@" else v) for k, v in row.items()})


def server_input(args: argparse.Namespace, cw: CleanedWeb) -> dict:
    """Translate the flags into the API's own inputs, using menu values read from its contract.json."""
    if args.source == "blocket":
        props = cw.contract(BLOCKET["slug"])["endpoints"][0]["input_schema"]["properties"]
        data: dict[str, Any] = {"sort": "PRICE_ASC"}
        if args.min_year:
            data["year_from"] = args.min_year
        if args.max_price:
            data["price_to"] = int(args.max_price)
        for flag, name in (("make", "variant"),):
            wanted = getattr(args, flag)
            if not wanted:
                continue
            menu = input_values(props[name])
            match = next((v for k, v in menu.items() if k.lower() == wanted.lower()), None)
            if match is None:
                sys.exit(f"'{wanted}' is not in the contract's {name} menu. Try --list-makes (makes) or read contract.json.")
            data[name] = match
        return data
    data = {}
    if args.keyword:
        data["auto_make_model"] = args.keyword[0]
    if args.min_year:
        data["min_auto_year"] = args.min_year
    if args.max_price:
        data["max_price"] = int(args.max_price)
    return data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", choices=list(SOURCES), default="blocket")
    p.add_argument("--make", help="Blocket only: a make from the contract's variant menu, e.g. Volvo")
    p.add_argument("--min-year", type=int)
    p.add_argument("--max-price", type=float)
    p.add_argument("--max-mileage", type=float, help="in the source's unit: km for blocket, miles for craigslist")
    p.add_argument("--fuel", help="substring of the listing's fuel, e.g. diesel, Bensin (applied to the records you read)")
    p.add_argument("--transmission", help="substring, e.g. manual, Automatisk")
    p.add_argument("--keyword", action="append", help="must appear in the title (repeatable)")
    p.add_argument("--min-discount", type=float, default=10.0, help="percent below the comparables' median (default 10)")
    p.add_argument("--max-items", type=int, default=100, help="records to read; every record delivered is charged")
    p.add_argument("--out", default="out")
    p.add_argument("--list-makes", action="store_true", help="print the Blocket make menu from contract.json (no key)")
    p.add_argument("--sample", action="store_true", help="use synthetic sample records instead of running an API")
    args = p.parse_args(argv)

    if args.list_makes:
        prop = CleanedWeb().contract(BLOCKET["slug"])["endpoints"][0]["input_schema"]["properties"]["variant"]
        status = dict(zip(prop["x-enum-labels"], prop.get("x-value-status", [])))
        shown = list(input_values(prop).items())[:40]
        print(f"{len(input_values(prop))} entries in the variant menu; the first 40 (code - label):")
        for label, code in shown:
            print(f"  {code:>8} - {label}")
        print(f"Values the contract marks 'verified': {sum(1 for s in status.values() if s == 'verified')}; the rest are 'observed' and the site may refuse them.")
        return 0

    normalize = SOURCES[args.source][1]
    if args.sample:
        records = json.loads((Path(__file__).parent / "sample" / f"{args.source}.json").read_text(encoding="utf-8"))
        print(f"Using {len(records)} synthetic sample records (no API run).")
    else:
        cw = CleanedWeb()
        try:
            result = cw.run(
                SOURCES[args.source][0]["api_id"], input=server_input(args, cw), max_items=args.max_items,
                state_dir=args.out, label=f"cars-{args.source}",
            )
        except CleanedWebError as error:
            print(f"error ({error.kind}): {error}", file=sys.stderr)
            return 1
        records = result.records
        print(f"Run {result.run_id}: {len(records)} records ({result.stop_reason}), {result.units_charged} Units charged.")

    cars = [c for c in (normalize(r) for r in records) if passes(c, args)]
    print(f"{len(cars)} of {len(records)} listings pass the filters.")
    deals = rank(cars, args.min_discount)
    if not deals:
        print(f"No listing is {args.min_discount:.0f}% or more below the median of at least 3 comparable cars. "
              "Read more records (--max-items) or lower --min-discount.")
    else:
        print_table(deals)
    write_csv(Path(args.out) / "deals.csv", deals)
    print(f"Wrote {len(deals)} deals to {Path(args.out) / 'deals.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
