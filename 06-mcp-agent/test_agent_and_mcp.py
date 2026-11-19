import asyncio
import json
import unittest

import httpx

from mcp_public_demo import McpClient


def mock_server(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


class McpClientTests(unittest.TestCase):
    def test_json_rpc_round_trip_and_tool_text_is_decoded(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            seen.append((body["method"], dict(request.headers)))
            if body["method"] == "tools/call":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": '{"count": 1}'}]}})
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"tools": []}})

        mcp = McpClient(client=mock_server(handler))
        self.assertEqual(mcp.call("find_api", {"site": "x"}), {"count": 1})
        self.assertEqual(mcp.list_tools(), [])
        self.assertEqual(seen[0][1]["mcp-protocol-version"], "2025-06-18")
        self.assertNotIn("authorization", seen[0][1])  # the public profile gets no key

    def test_errors_are_raised(self):
        def handler(request):
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "nope"}})

        with self.assertRaises(RuntimeError):
            McpClient(client=mock_server(handler)).rpc("x")


try:
    import agent  # needs claude-agent-sdk
except ImportError:  # the MCP tests above still run without the SDK
    agent = None


@unittest.skipIf(agent is None, "claude-agent-sdk is not installed")
class AgentGuardTests(unittest.TestCase):
    good = {"api_id": "generated_x", "endpoint_id": "generated_x_search", "max_items": 5, "idempotency_key": "demo-1", "input": {}}

    def test_guard(self):
        self.assertIsNone(agent.guard_run_api(self.good, 10))
        self.assertIn("max_items", agent.guard_run_api({**self.good, "max_items": 500}, 10))
        self.assertIn("max_items", agent.guard_run_api({k: v for k, v in self.good.items() if k != "max_items"}, 10))
        self.assertIn("max_items", agent.guard_run_api({**self.good, "max_items": True}, 10))
        self.assertIn("idempotency_key", agent.guard_run_api({**self.good, "idempotency_key": "has space"}, 10))
        self.assertIn("catalog APIs", agent.guard_run_api({**self.good, "source_id": "mine"}, 10))

    def test_callback_denies_other_tools_and_bad_runs_without_prompting(self):
        callback = agent.make_permission_callback(10, auto_yes=False)
        denied = asyncio.run(callback("Bash", {"command": "ls"}, None))
        self.assertEqual(denied.behavior, "deny")
        bad = asyncio.run(callback(agent.RUN, {**self.good, "max_items": 999}, None))
        self.assertEqual(bad.behavior, "deny")

    def test_callback_allows_a_guarded_run_with_yes(self):
        callback = agent.make_permission_callback(10, auto_yes=True)
        self.assertEqual(asyncio.run(callback(agent.RUN, self.good, None)).behavior, "allow")

    def test_options(self):
        read_only = agent.build_options(False, None, 10, False, 12, 1.0)
        self.assertEqual(read_only.mcp_servers["cleanedweb"]["url"], agent.MCP_PUBLIC)
        self.assertNotIn("headers", read_only.mcp_servers["cleanedweb"])
        self.assertEqual(read_only.tools, [])
        self.assertIsNone(read_only.can_use_tool)
        with_run = agent.build_options(True, "k", 10, False, 12, 1.0)
        self.assertEqual(with_run.mcp_servers["cleanedweb"]["headers"], {"Authorization": "Bearer k"})
        self.assertNotIn(agent.RUN, with_run.allowed_tools)
        with self.assertRaises(SystemExit):
            agent.build_options(True, None, 10, False, 12, 1.0)


if __name__ == "__main__":
    unittest.main()
