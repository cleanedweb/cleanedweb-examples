#!/usr/bin/env python3
"""Summarize how a committed JSON data file changed between two git revisions, as Markdown.

    python summarize_diff.py data/dev-mcp-articles.json                # HEAD~1 -> HEAD
    python summarize_diff.py data/x.json --old HEAD~3 --new HEAD --key url --title title

Records are matched by --key (default `url`). The file is a bounded sample of a website, so "no longer in
the file" is not "deleted from the website".  Website text is cleaned (control characters, length) and
Markdown-escaped before it is printed, because the output is posted to a job summary.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any


def git_show(rev: str, path: str) -> list[dict] | None:
    result = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True, text=True)
    if result.returncode != 0:
        return None  # the file did not exist at that revision
    data = json.loads(result.stdout)
    return data if isinstance(data, list) else None


def md(value: Any, limit: int = 100) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value if value is not None else ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1] + "..."
    return re.sub(r"([\\`*_{}\[\]<>()#+!|~@&])", r"\\\1", text)


def compare(old: list[dict], new: list[dict], key: str) -> dict[str, list]:
    old_by = {r[key]: r for r in old if isinstance(r, dict) and r.get(key)}
    new_by = {r[key]: r for r in new if isinstance(r, dict) and r.get(key)}
    changed = []
    for k, record in new_by.items():
        before = old_by.get(k)
        if before is not None and before != record:
            fields = sorted(f for f in set(before) | set(record) if before.get(f) != record.get(f))
            changed.append((record, fields))
    return {
        "added": [r for k, r in new_by.items() if k not in old_by],
        "gone": [r for k, r in old_by.items() if k not in new_by],
        "changed": changed,
    }


def render(path: str, old: list[dict] | None, new: list[dict], key: str, title: str, limit: int = 20) -> str:
    lines = [f"### Data update: `{md(path)}`", ""]
    if old is None:
        return "\n".join(lines + [f"First snapshot: {len(new)} records.", ""])
    diff = compare(old, new, key)
    lines.append(f"{len(new)} records now ({len(old)} before): {len(diff['added'])} new, {len(diff['changed'])} changed, {len(diff['gone'])} no longer in the file.")
    lines.append("")
    if diff["added"]:
        lines.append("**New**")
        lines += [f"- {md(r.get(title) or r.get(key))}" for r in diff["added"][:limit]]
        lines.append("")
    if diff["changed"]:
        lines.append("**Changed**")
        lines += [f"- {md(r.get(title) or r.get(key))}: {', '.join(md(f, 30) for f in fields[:6])}" for r, fields in diff["changed"][:limit]]
        lines.append("")
    if diff["gone"]:
        lines.append(f"**No longer in the file** ({len(diff['gone'])}): the run is bounded, so this does not mean the website removed them.")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path")
    p.add_argument("--old", default="HEAD~1")
    p.add_argument("--new", default="HEAD")
    p.add_argument("--key", default="url")
    p.add_argument("--title", default="title")
    args = p.parse_args(argv)
    new = git_show(args.new, args.path)
    if new is None:
        print(f"{args.path} is not a JSON array at {args.new}", file=sys.stderr)
        return 1
    print(render(args.path, git_show(args.old, args.path), new, args.key, args.title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
