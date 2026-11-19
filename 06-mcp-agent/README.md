# 06 - An AI agent that finds and runs an API through MCP

CleanedWeb is an MCP server. An agent connected to it can search the catalog (`find_api`), read an API's inputs, limitations and sample records (`get_api`), and run it (`run_api`). This example shows two ways in:

| File | What | Key needed | Cost |
| --- | --- | --- | --- |
| `mcp_public_demo.py` | The MCP protocol by hand: JSON-RPC over HTTP with `httpx`, public profile | none | free; runs nothing |
| `agent.py` | A [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview) agent that finds an API for your request; with `--allow-run` it can also run it | none for read-only; `CLEANEDWEB_API_KEY` for `--allow-run` | read-only: only the model's own tokens. `--allow-run`: charged per record delivered |

> The official `cleanedweb` SDKs for Python and JavaScript are coming. This example does not use them: `mcp_public_demo.py` talks to the server directly, `agent.py` uses the Claude Agent SDK.

## Try the protocol (free, no key)

```bash
pip install -r requirements.txt
python mcp_public_demo.py                                          # find APIs for www.blocket.se
python mcp_public_demo.py --topic "github repositories" --get      # topic search, then get_api on the first match
```

```
Connected to cleanedweb-builder (protocol 2025-06-18)
Tools on the public profile: find_api, get_api
find_api {'limit': 5, 'site': 'www.blocket.se'}: 1 of 1 matches
- Blocket Vehicle Listings (www.blocket.se)
    api_id generated_c339677c254f69a380ef3a54  endpoint generated_c339677c254f69a380ef3a54_search
...
run_with (what an agent with a key would call; nothing was run):
```

The server is `https://api.cleanedweb.com/mcp?profile=public`: plain JSON responses, no sessions, no streams. `find_api` returns each match's fields, inputs and a ready-made `run_with` call; `get_api` adds coverage, limitations, health and three saved sample records. See [connect an MCP client](https://cleanedweb.com/docs/mcp/?utm_source=github&utm_medium=cleanedweb-examples).

## Run the agent

The agent needs credentials for **its own model**: `ANTHROPIC_API_KEY`, or a signed-in Claude Code. That is separate from the CleanedWeb key.

Read-only (the default; the agent only searches and reads):

```bash
python agent.py "Find an API for DEV Community articles and tell me which input selects a tag"
python agent.py     # default prompt: GitHub topic repositories
```

With running enabled, for a CleanedWeb key that has the `read` and `run` scopes:

```bash
export CLEANEDWEB_API_KEY=...
python agent.py --allow-run --max-records 5 "Find an API for GitHub repositories about web scraping, run it for 5 records, and list the names"
```

Cost: `run_api` is charged per record delivered (5,000 free once, then prepaid from $1 per 1,000). Three guards sit between the model and your credit:

1. **Code, not prompting.** `guard_run_api` refuses any `run_api` call without an integer `max_items` between 1 and `--max-records` (default 10), without a valid `idempotency_key`, or for anything but a catalog API.
2. **You confirm.** Each allowed call is printed and waits for `y` (skip with `--yes`; the guard still applies).
3. **Least tools.** `tools=[]` removes the built-in shell and file tools; the only tools are `find_api`, `get_api` and (with `--allow-run`) `run_api`. The model's own spend is capped with `--max-budget-usd` and `--max-turns`.

## Values in records are website data

Records come from public websites; any text in them could say "ignore your instructions". The system prompt says to treat record values as data, but the real protection is the guard above: even a fooled agent cannot run more than `--max-records`, cannot spend through any tool other than `run_api`, and cannot touch your files or shell. Keep it that way if you extend the agent.

## Things to know

- **Very large `find_api` answers.** An API with huge menus (Blocket's make and location menus have thousands of entries) returns an answer too large for the model's context, which the client saves to a file. With `tools=[]` the agent cannot read it. Search by `topic` or pick a smaller API, or give the agent a tool to read that file if you need such APIs.
- `find_api` returns `next: "request_source"` when no API covers a site; with a key, `request_source` asks CleanedWeb to add it (nothing is built or charged).
- OAuth sign-in works in apps such as Claude, Cursor and ChatGPT; a script uses an API key as above. A key can run APIs, so keep it in a secret store.
- The agent shown here is deliberately small. A production agent should persist idempotency keys per intended run: the same key and arguments answer the same run and never charge twice.

## Files

`mcp_public_demo.py`, `agent.py`, `test_agent_and_mcp.py` (`python test_agent_and_mcp.py`; the guard tests skip if `claude-agent-sdk` is not installed).
