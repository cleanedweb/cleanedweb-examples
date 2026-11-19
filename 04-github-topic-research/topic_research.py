#!/usr/bin/env python3
"""GitHub topic research: rank the repositories listed under a topic and see what else they are tagged with.

Source: the "GitHub Topics Repositories" catalog API (the public repositories listed on github.com/topics/<topic>).
A run is charged per record delivered.

    export CLEANEDWEB_API_KEY=...
    python topic_research.py --topic web-scraping --language Python --max-items 50

    python topic_research.py --sample       # offline demo on synthetic records, no key, no charge

Output: out/<topic>-ranking.md (a table), out/<topic>-ranking.csv and a short summary on stdout.
Stars and forks come from each repository's own page, so only enriched records carry them: records without
a count are listed as "unknown", never as zero.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from cw_http import CleanedWeb, CleanedWebError, clean_text

API_ID = "generated_047a8ebb25911ccf62f4a212"  # GitHub Topics Repositories
SORTS = ["desc_stars", "asc_stars", "desc_forks", "asc_forks", "desc_updated", "asc_updated"]


def count(value: Any) -> int | None:
    """An integer count or None. Accepts the typed_* integers and text such as "1,234"; a missing value is not 0."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().replace(",", "")
    return int(text) if re.fullmatch(r"\d+", text) else None


def repo_row(record: dict) -> dict:
    return {
        "name": record.get("title"),
        "owner": record.get("owner_login"),
        "url": record.get("url"),
        "stars": count(record.get("typed_stargazer_count")) if record.get("typed_stargazer_count") is not None else count(record.get("stargazer_count")),
        "forks": count(record.get("typed_forks_count")) if record.get("typed_forks_count") is not None else count(record.get("forks_count")),
        "language": record.get("programming_language"),
        "description": record.get("description"),
        "topics": [t for t in (record.get("topics") or []) if isinstance(t, str)],
    }


def rank(records: list[dict]) -> list[dict]:
    """Stars descending, forks as the tie-break; repositories without a star count go last. Duplicates by URL are dropped."""
    seen: set[str] = set()
    rows = []
    for record in records:
        row = repo_row(record)
        if not row["url"] or row["url"] in seen:
            continue
        seen.add(row["url"])
        rows.append(row)
    rows.sort(key=lambda r: (r["stars"] is None, -(r["stars"] or 0), -(r["forks"] or 0), str(r["name"]).lower()))
    for position, row in enumerate(rows, 1):
        row["rank"] = position
    return rows


def related_topics(rows: list[dict], queried: str, top: int = 10) -> list[tuple[str, int]]:
    counts = Counter(t for r in rows for t in set(r["topics"]) if t != queried)
    return counts.most_common(top)


def languages(rows: list[dict]) -> list[tuple[str, int]]:
    return Counter(r["language"] for r in rows if r["language"]).most_common()


def md_cell(value: Any, limit: int = 90) -> str:
    """Website text inside a Markdown table: no pipes, no HTML, no line breaks."""
    text = clean_text(value, limit)
    return text.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def md_link(name: str, url: str) -> str:
    """A link only for http(s) URLs, with the characters that end a Markdown link encoded."""
    if not re.match(r"^https?://", str(url)):
        return name
    return f"[{name}]({str(url).replace(' ', '%20').replace('(', '%28').replace(')', '%29')})"


def markdown(topic: str, rows: list[dict]) -> str:
    known = sum(1 for r in rows if r["stars"] is not None)
    lines = [
        f"# GitHub topic: {md_cell(topic)}",
        "",
        f"{len(rows)} repositories read; {known} with a star count, {len(rows) - known} unknown (not enriched).",
        "",
        "| # | Repository | Stars | Forks | Language | Description |",
        "| ---: | --- | ---: | ---: | --- | --- |",
    ]
    for r in rows:
        stars = f"{r['stars']:,}" if r["stars"] is not None else "unknown"
        forks = f"{r['forks']:,}" if r["forks"] is not None else "unknown"
        lines.append(f"| {r['rank']} | {md_link(md_cell(r['name'], 60), r['url'])} | {stars} | {forks} | {md_cell(r['language'], 30)} | {md_cell(r['description'])} |")
    lines += ["", "Related topics: " + ", ".join(f"{md_cell(t, 40)} ({n})" for t, n in related_topics(rows, topic)), ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--topic", default="web-scraping", help="a GitHub topic, e.g. web-scraping, machine-learning")
    p.add_argument("--language", help="only repositories in this language, e.g. Python")
    p.add_argument("--sort", choices=SORTS, default="desc_stars", help="the topic page's own order (what the run reads first)")
    p.add_argument("--max-items", type=int, default=50, help="repositories to read; every record delivered is charged")
    p.add_argument("--top", type=int, default=15, help="how many to print")
    p.add_argument("--out", default="out")
    p.add_argument("--sample", action="store_true", help="use synthetic sample records instead of running the API")
    args = p.parse_args(argv)

    if args.sample:
        records = json.loads((Path(__file__).parent / "sample" / "records.json").read_text(encoding="utf-8"))
        print(f"Using {len(records)} synthetic sample records (no API run).")
    else:
        inputs: dict[str, Any] = {"topics": args.topic, "sort": args.sort}
        if args.language:
            inputs["programming_language"] = args.language
        try:
            result = CleanedWeb().run(API_ID, input=inputs, max_items=args.max_items, state_dir=args.out, label=f"topic-{args.topic}")
        except CleanedWebError as error:
            print(f"error ({error.kind}): {error}", file=sys.stderr)
            return 1
        records = result.records
        print(f"Run {result.run_id}: {len(records)} records ({result.stop_reason}), {result.units_charged} Units charged.")

    rows = rank(records)
    if not rows:
        print("No repositories returned; nothing written.", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", args.topic)
    (out / f"{slug}-ranking.md").write_text(markdown(args.topic, rows), encoding="utf-8")
    with (out / f"{slug}-ranking.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["rank", "name", "owner", "stars", "forks", "language", "url", "topics"])
        for r in rows:
            cells = [r["rank"], r["name"], r["owner"], r["stars"], r["forks"], r["language"], r["url"], " ".join(r["topics"])]
            writer.writerow(["'" + c if isinstance(c, str) and c[:1] in "=+-@" else c for c in cells])

    print(f"\nTop {min(args.top, len(rows))} of {len(rows)} for topic '{args.topic}':")
    for r in rows[: args.top]:
        stars = f"{r['stars']:>8,}" if r["stars"] is not None else "       ?"
        print(f"  {r['rank']:>3}. {stars} stars  {clean_text(r['name'], 40):<40} {clean_text(r['language'] or '', 14):<14} {r['url']}")
    print("\nLanguages: " + ", ".join(f"{k} {v}" for k, v in languages(rows)[:6]))
    print("Related topics: " + ", ".join(f"{t} ({n})" for t, n in related_topics(rows, args.topic, 8)))
    print(f"\nWrote {out / (slug + '-ranking.md')} and {out / (slug + '-ranking.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
