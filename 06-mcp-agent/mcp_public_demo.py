#!/usr/bin/env python3
"""Talk to the CleanedWeb MCP server by hand: no SDK, no API key, no LLM, no charge.

The public profile (https://api.cleanedweb.com/mcp?profile=public) lists two tools without signing in:
`find_api` (search the catalog) and `get_api` (one API: coverage, limitations, inputs, saved sample records).
MCP over HTTP here is plain JSON-RPC (no sessions, no streams), so httpx is enough.

    python mcp_public_demo.py                              # find APIs for a site
    python mcp_public_demo.py --site www.blocket.se --field title --field price
    python mcp_public_demo.py --topic "github repositories" --get      # also read the first match with get_api

Nothing here runs an API; `run_api` needs a key and is charged per record delivered (see agent.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx

MCP_PUBLIC_URL = "https://api.cleanedweb.com/mcp?profile=public"
PROTOCOL = "2025-06-18"


class McpClient:
    def __init__(self, url: str = MCP_PUBLIC_URL, headers: dict[str, str] | None = None, client: httpx.Client | None = None):
        self.url = url
        self.http = client or httpx.Client(timeout=60, follow_redirects=False)
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL,
            **(headers or {}),
        }
        self._id = 0

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": method, **({"params": params} if params is not None else {})}
        response = self.http.post(self.url, json=body, headers=self.headers)
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(f"MCP error: {payload['error']}")
        return payload["result"]

    def initialize(self) -> dict:
        return self.rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "cleanedweb-examples", "version": "0.1"}})

    def list_tools(self) -> list[dict]:
        return self.rpc("tools/list")["tools"]

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool; the answer is JSON text in result.content[0].text."""
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        text = "".join(block.get("text", "") for block in result.get("content", []) if block.get("type") == "text")
        if result.get("isError"):
            raise RuntimeError(f"tool {name} failed: {text[:300]}")
        try:
            return json.loads(text)
        except ValueError:
            return text


def summarize_match(match: dict) -> str:
    inputs = ", ".join(i["name"] for i in match.get("inputs", [])[:8])
    return (
        f"- {match['name']} ({match['site']['domain']})\n"
        f"    api_id {match['api_id']}  endpoint {match['endpoint_id']}\n"
        f"    fields matched {match.get('fields_matched')}  missing {match.get('fields_missing')}\n"
        f"    inputs: {inputs or '(none)'}"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--site", default="www.blocket.se")
    p.add_argument("--topic")
    p.add_argument("--field", action="append", default=None, help="an output field you need (repeatable)")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--get", action="store_true", help="also call get_api on the first match")
    args = p.parse_args(argv)

    mcp = McpClient()
    info = mcp.initialize()
    print(f"Connected to {info['serverInfo']['name']} (protocol {info['protocolVersion']})")
    print("Tools on the public profile:", ", ".join(t["name"] for t in mcp.list_tools()))

    arguments: dict[str, Any] = {"limit": args.limit}
    if args.site and not args.topic:
        arguments["site"] = args.site
    if args.topic:
        arguments["topic"] = args.topic
    if args.field:
        arguments["fields"] = args.field
    found = mcp.call("find_api", arguments)
    print(f"\nfind_api {arguments}: {found['count']} of {found['total']} matches")
    for match in found["matches"]:
        print(summarize_match(match))
    if not found["matches"]:
        print("No match. With a key, `request_source` can ask for a site the catalog does not cover.")
        return 0

    first = found["matches"][0]
    print("\nrun_with (what an agent with a key would call; nothing was run):")
    print(json.dumps(first["run_with"]["arguments"], indent=2)[:600])
    if args.get:
        api = mcp.call("get_api", {"api_id": first["api_id"]})
        print(f"\nget_api {first['api_id']}: keys {sorted(api)[:12]}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except httpx.HTTPError as error:
        print(f"request failed: {error}", file=sys.stderr)
        raise SystemExit(1)
