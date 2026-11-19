#!/usr/bin/env python3
"""Price monitor: run a catalog API on a schedule, compare prices with the last run, and alert on changes.

Default source: Thomann "Ukuleles and Accessories" (a product listing with `price`, `currency`, `brand`,
`item_name`, `url`). Point it at any catalog API whose records have a stable id (`url`) and a numeric price.

    export CLEANEDWEB_API_KEY=...            # run scope; runs are charged per record delivered
    python price_monitor.py --max-items 25   # first run saves a baseline, later runs report changes

    python price_monitor.py --from-file sample/day1.json   # offline demo, no key, no charge
    python price_monitor.py --from-file sample/day2.json   # ... prints the changes between the two days
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from cw_http import CleanedWeb, CleanedWebError, clean_text

THOMANN_UKULELES = "generated_ef2595d47b91cc608bbec022"


def to_price(value: Any) -> float | None:
    """A price as a number, or None when the page did not show one. A missing price is not zero."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = re.sub(r"[^\d.,-]", "", value)
        if text.count(",") and text.count("."):
            text = text.replace(",", "") if text.rfind(".") > text.rfind(",") else text.replace(".", "").replace(",", ".")
        elif text.count(","):
            text = text.replace(",", ".") if len(text.rsplit(",", 1)[-1]) <= 2 else text.replace(",", "")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def normalize(records: list[dict], key_field: str, name_fields: list[str], price_field: str, currency_field: str) -> dict[str, dict]:
    """{id: {name, price, currency}} for records that have an id and a price. Duplicates keep the first."""
    out: dict[str, dict] = {}
    for record in records:
        key = record.get(key_field)
        price = to_price(record.get(price_field))
        if not key or price is None or key in out:
            continue
        name = " ".join(str(record[f]) for f in name_fields if record.get(f)) or str(key)
        out[str(key)] = {"name": clean_text(name, 120), "price": price, "currency": record.get(currency_field) or ""}
    return out


def diff_snapshots(old: dict[str, dict], new: dict[str, dict], min_change_pct: float = 1.0) -> dict[str, list]:
    """Compare two snapshots. `not_seen` is NOT a removal: a bounded run only reads part of the source."""
    changes: dict[str, list] = {"drops": [], "rises": [], "new": [], "not_seen": []}
    for key, item in new.items():
        before = old.get(key)
        if before is None:
            changes["new"].append((key, item))
            continue
        if before["price"] == 0:
            continue
        pct = (item["price"] - before["price"]) / before["price"] * 100
        if abs(pct) >= min_change_pct:
            (changes["drops"] if pct < 0 else changes["rises"]).append((key, item, before["price"], pct))
    changes["not_seen"] = [(k, v) for k, v in old.items() if k not in new]
    changes["drops"].sort(key=lambda c: c[3])
    changes["rises"].sort(key=lambda c: -c[3])
    return changes


def money(price: float, currency: str) -> str:
    return f"{price:,.2f} {currency}".strip()


def format_report(changes: dict[str, list], limit: int = 15) -> str:
    lines = []
    for title, rows in (("Price drops", changes["drops"]), ("Price rises", changes["rises"])):
        if rows:
            lines.append(f"{title} ({len(rows)})")
            for key, item, before, pct in rows[:limit]:
                lines.append(f"  {item['name']}: {money(before, item['currency'])} -> {money(item['price'], item['currency'])} ({pct:+.1f}%)  {key}")
    if changes["new"]:
        lines.append(f"New in this run ({len(changes['new'])})")
        for key, item in changes["new"][:limit]:
            lines.append(f"  {item['name']}: {money(item['price'], item['currency'])}  {key}")
    if changes["not_seen"]:
        lines.append(
            f"Not in this run: {len(changes['not_seen'])} earlier items. That is not a removal: a run limited by "
            "--max-items sees only part of the source."
        )
    return "\n".join(lines)


def send_webhook(url: str, text: str) -> None:
    """Post a plain-text summary ({"text": ...}, the shape Slack incoming webhooks accept)."""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # website text must not become mentions or links
    httpx.post(url, json={"text": escaped[:3500]}, timeout=15, follow_redirects=False).raise_for_status()


def append_history(path: Path, snapshot: dict[str, dict]) -> None:
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(["observed_at", "id", "name", "price", "currency"])
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for key, item in snapshot.items():
            writer.writerow([now, key, item["name"], item["price"], item["currency"]])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api-id", default=THOMANN_UKULELES, help="catalog api_id (default: Thomann Ukuleles and Accessories)")
    p.add_argument("--input", default='{"manufacturer": "Kala"}', help="API input as a JSON object (see the API's contract.json)")
    p.add_argument("--max-items", type=int, default=25, help="stop after this many records (every record delivered is charged)")
    p.add_argument("--key-field", default="url")
    p.add_argument("--name-fields", default="brand,item_name", help="comma-separated fields that make up the display name")
    p.add_argument("--price-field", default="price")
    p.add_argument("--currency-field", default="currency")
    p.add_argument("--min-change-pct", type=float, default=1.0, help="ignore changes smaller than this (default 1.0)")
    p.add_argument("--out", default="out", help="folder for the snapshot and history (gitignored)")
    p.add_argument("--from-file", help="read records from a JSON file instead of running the API (offline, no charge)")
    p.add_argument("--webhook", default=os.environ.get("ALERT_WEBHOOK_URL"), help="post alerts here (env ALERT_WEBHOOK_URL)")
    args = p.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.from_file:
        records = json.loads(Path(args.from_file).read_text(encoding="utf-8"))
        print(f"Read {len(records)} records from {args.from_file} (no API run).")
    else:
        try:
            result = CleanedWeb().run(
                args.api_id, input=json.loads(args.input), max_items=args.max_items, state_dir=out, label="price-monitor"
            )
        except CleanedWebError as error:
            print(f"error ({error.kind}): {error}", file=sys.stderr)
            return 1
        records = result.records
        print(f"Run {result.run_id}: {len(records)} records ({result.stop_reason}), {result.units_charged} Units charged.")

    snapshot = normalize(records, args.key_field, args.name_fields.split(","), args.price_field, args.currency_field)
    if not snapshot:
        print("No record had both an id and a price; the saved snapshot was left untouched.", file=sys.stderr)
        return 1

    state = out / "prices.json"
    previous = json.loads(state.read_text(encoding="utf-8")) if state.exists() else None
    if previous is None:
        print(f"Baseline saved: {len(snapshot)} items. Run again later to see changes.")
    else:
        changes = diff_snapshots(previous, snapshot, args.min_change_pct)
        report = format_report(changes)
        print(report or "No price changes.")
        if args.webhook and (changes["drops"] or changes["rises"]):
            send_webhook(args.webhook, report)
            print("Alert posted to the webhook.")

    merged = {**(previous or {}), **snapshot}  # keep items this bounded run did not see
    state.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    append_history(out / "history.csv", snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
