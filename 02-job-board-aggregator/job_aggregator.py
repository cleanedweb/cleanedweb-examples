#!/usr/bin/env python3
"""Job-board aggregator: pull listings from several catalog APIs, normalize them and write one CSV.

Sources (each is a published catalog API; a run is charged per record delivered):
  yc    Y Combinator startup jobs. Needs a `category` input such as "san-francisco" or "new-york".
  pph   PeoplePerHour freelance jobs.

    export CLEANEDWEB_API_KEY=...
    python job_aggregator.py --sources yc,pph --yc-category san-francisco --max-items 25 --keyword python

    python job_aggregator.py --sample        # offline demo from synthetic sample records, no key, no charge

Output: out/jobs.csv with columns source, title, company, location, type, pay, posted, url.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

from cw_http import CleanedWeb, CleanedWebError, clean_text

COLUMNS = ["source", "title", "company", "location", "type", "pay", "posted", "url"]
_MONEY = re.compile(r"^[£$€]\s?\d")


def normalize_yc(r: dict) -> dict:
    return {
        "title": r.get("title"),
        "company": r.get("company_name") or r.get("detail_company_name"),
        "location": r.get("location"),
        "type": r.get("type"),
        "pay": r.get("salary_range") or r.get("detail_salary_range"),  # text as posted, e.g. "$280K - $325K"
        "posted": r.get("created_at"),  # relative text such as "3 days", as the site shows it
        "url": r.get("url"),
    }


def normalize_pph(r: dict) -> dict:
    nano = r.get("title_nano") or ""
    return {
        "title": r.get("title"),
        "company": r.get("client_name") or r.get("author_name"),
        "location": r.get("client_country"),
        "type": r.get("price_type") or r.get("budget_type"),
        "pay": nano if _MONEY.match(nano) else "",  # only when it looks like an amount, e.g. "$1.3K"
        "posted": r.get("posted_time") or r.get("date"),
        "url": r.get("url"),
    }


SOURCES: dict[str, dict[str, Any]] = {
    "yc": {"api_id": "generated_454e4018e68f42abac465d27", "normalize": normalize_yc, "sample": "sample/yc.json"},
    "pph": {"api_id": "generated_10d258ade87f41daf26d17bc", "normalize": normalize_pph, "sample": "sample/pph.json"},
}


def spreadsheet_safe(value: Any) -> str:
    """Website text can start with = + - @ and be run as a formula by a spreadsheet; mark it as text."""
    text = clean_text(value, 500)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def aggregate(batches: list[tuple[str, list[dict]]], keywords: list[str] | None = None) -> list[dict]:
    """Normalize and de-duplicate by URL (first source wins). Keywords match any column, case-insensitively."""
    seen: set[str] = set()
    rows: list[dict] = []
    for source, records in batches:
        normalize: Callable[[dict], dict] = SOURCES[source]["normalize"]
        for record in records:
            row = normalize(record)
            url = row.get("url")
            if not row.get("title") or not url or url in seen:
                continue
            if keywords:
                haystack = " ".join(str(v) for v in row.values()).lower() + " " + str(record.get("description", "")).lower()
                if not any(k.lower() in haystack for k in keywords):
                    continue
            seen.add(url)
            rows.append({"source": source, **{c: spreadsheet_safe(row.get(c)) for c in COLUMNS[1:]}})
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sources", default="yc,pph", help="comma-separated: " + ", ".join(SOURCES))
    p.add_argument("--yc-category", default="san-francisco", help="YC jobs page, e.g. san-francisco, new-york, seattle")
    p.add_argument("--max-items", type=int, default=25, help="per source; every record delivered is charged")
    p.add_argument("--keyword", action="append", help="keep rows that mention this (repeatable, any match)")
    p.add_argument("--out", default="out")
    p.add_argument("--sample", action="store_true", help="use the synthetic sample records instead of running APIs")
    args = p.parse_args(argv)

    chosen = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = [s for s in chosen if s not in SOURCES]
    if unknown:
        p.error(f"unknown source(s): {', '.join(unknown)}")

    batches: list[tuple[str, list[dict]]] = []
    cw = None if args.sample else CleanedWeb()
    for source in chosen:
        if args.sample:
            records = json.loads((Path(__file__).parent / SOURCES[source]["sample"]).read_text(encoding="utf-8"))
        else:
            inputs = {"category": args.yc_category} if source == "yc" else {}
            try:
                result = cw.run(SOURCES[source]["api_id"], input=inputs, max_items=args.max_items, state_dir=args.out, label=f"jobs-{source}")
            except CleanedWebError as error:
                print(f"{source}: error ({error.kind}): {error}", file=sys.stderr)
                continue  # keep the other sources
            records = result.records
            print(f"{source}: run {result.run_id}, {len(records)} records, {result.units_charged} Units charged")
        batches.append((source, records))

    if not batches:
        print("No source returned records; nothing written.", file=sys.stderr)
        return 1
    rows = aggregate(batches, args.keyword)
    target = Path(args.out) / "jobs.csv"
    write_csv(target, rows)
    print(f"Wrote {len(rows)} jobs to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
