import json
import tempfile
import unittest
from pathlib import Path

import httpx

from cw_http import CleanedWeb, CleanedWebError, clean_text, input_values

RUN = "b" * 32


def ok(records, status="completed"):
    return {
        "records": records,
        "summary": {"status": status, "within_scope_passed": True, "records": len(records)},
        "run": {"run_id": "a" * 32, "stop_reason": "max_items", "units_charged": len(records)},
        "delivery": {"runId": "a" * 32, "recordCount": len(records)},
    }


def client(steps):
    """A CleanedWeb whose HTTP answers come from a queue of (status, body, headers) or Exceptions."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"method": request.method, "url": str(request.url), "headers": dict(request.headers), "body": json.loads(request.content) if request.content else None})
        step = steps.pop(0)
        if isinstance(step, Exception):
            raise step
        status, body, headers = (step + ({},))[:3] if len(step) == 2 else step
        return httpx.Response(status, json=body, headers=headers)

    sleeps = []
    cw = CleanedWeb("sk-secret", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append)
    cw.calls, cw.sleeps = calls, sleeps
    return cw


class RunTests(unittest.TestCase):
    def test_request_shape_and_200(self):
        cw = client([(200, ok([{"a": 1}]))])
        result = cw.run("generated_x", input={"q": 1}, max_items=5)
        self.assertEqual(result.records, [{"a": 1}])
        call = cw.calls[0]
        self.assertEqual(call["url"], "https://broker.cleanedweb.com/v1/catalog/public/apis/generated_x/endpoints/generated_x_search/run")
        self.assertEqual(call["headers"]["authorization"], "Bearer sk-secret")
        self.assertRegex(call["headers"]["idempotency-key"], r"^example-")
        self.assertEqual(call["body"], {"input": {"q": 1}, "max_items": 5, "timeout_seconds": 1800, "wait_seconds": 90})

    def test_202_polls_result_with_same_key_and_never_reposts(self):
        pending = (202, {"run_id": RUN, "status": "running"}, {"Retry-After": "7"})
        cw = client([pending, pending, (200, ok([1]))])
        cw.run("generated_x", max_items=1)
        self.assertEqual([c["method"] for c in cw.calls], ["POST", "GET", "GET"])
        self.assertTrue(cw.calls[1]["url"].endswith("/endpoints/generated_x_search/result"))
        self.assertEqual({c["headers"]["idempotency-key"] for c in cw.calls}, {cw.calls[0]["headers"]["idempotency-key"]})
        self.assertEqual(cw.sleeps, [7.0, 7.0])

    def test_errors_are_explained(self):
        for status, body, kind in [
            (401, {"detail": "x"}, "auth"),
            (403, {}, "forbidden"),
            (402, {"detail": {"code": "insufficient_units", "required": 5, "available": 0}}, "credit"),
            (409, {"detail": {"code": "delivery_identity_conflict"}}, "conflict"),
            (404, {}, "not_found"),
            (422, {"detail": {"code": "bad", "message": "m"}}, "invalid"),
            (502, {"detail": {"error_code": "run_failed", "run_id": RUN}}, "run_failed"),
        ]:
            cw = client([(status, body)])
            with self.assertRaises(CleanedWebError) as raised:
                cw.run("generated_x", max_items=1)
            self.assertEqual(raised.exception.kind, kind, status)
            self.assertEqual(len(cw.calls), 1)
            self.assertNotIn("sk-secret", str(raised.exception))

    def test_429_waits_retry_after_and_retries_with_same_key(self):
        cw = client([(429, {}, {"Retry-After": "12"}), (200, ok([1]))])
        cw.run("generated_x", max_items=1)
        self.assertEqual(cw.sleeps, [12.0])
        self.assertEqual(cw.calls[0]["headers"]["idempotency-key"], cw.calls[1]["headers"]["idempotency-key"])

    def test_lost_connection_reads_result_instead_of_reposting(self):
        cw = client([httpx.ConnectError("boom"), (200, ok([1]))])
        cw.run("generated_x", max_items=1)
        self.assertEqual([c["method"] for c in cw.calls], ["POST", "GET"])

    def test_unknown_key_404_on_result_means_resend_same_key(self):
        cw = client([(503, {"detail": "down"}), (404, {}), (200, ok([1]))])
        cw.run("generated_x", max_items=1)
        self.assertEqual([c["method"] for c in cw.calls], ["POST", "GET", "POST"])

    def test_partial_result_is_refused(self):
        cw = client([(200, ok([1], status="partial"))])
        with self.assertRaises(CleanedWebError) as raised:
            cw.run("generated_x", max_items=1)
        self.assertEqual(raised.exception.kind, "review")

    def test_a_key_is_saved_before_sending_and_reused_for_the_same_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            cw = client([httpx.ConnectError("x")] * 6)
            cw._sleep = lambda s: None
            with self.assertRaises(CleanedWebError):
                cw.run("generated_x", input={"a": 1}, max_items=1, state_dir=tmp, label="t")
            saved = json.loads((Path(tmp) / ".pending-t.json").read_text())["key"]
            cw2 = client([(200, ok([1]))])
            cw2.run("generated_x", input={"a": 1}, max_items=1, state_dir=tmp, label="t")
            self.assertEqual(cw2.calls[0]["headers"]["idempotency-key"], saved)  # recovered, not a new run
            self.assertFalse((Path(tmp) / ".pending-t.json").exists())  # cleaned up after the run ended

    def test_a_changed_request_gets_a_new_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            cw = client([httpx.ConnectError("x")] * 6)
            cw._sleep = lambda s: None
            with self.assertRaises(CleanedWebError):
                cw.run("generated_x", input={"a": 1}, max_items=1, state_dir=tmp, label="t")
            saved = json.loads((Path(tmp) / ".pending-t.json").read_text())["key"]
            cw2 = client([(200, ok([1]))])
            cw2.run("generated_x", input={"a": 2}, max_items=1, state_dir=tmp, label="t")
            self.assertNotEqual(cw2.calls[0]["headers"]["idempotency-key"], saved)

    def test_needs_a_key(self):
        with self.assertRaises(CleanedWebError):
            CleanedWeb("", client=httpx.Client(transport=httpx.MockTransport(lambda r: None))).run("generated_x")


class HelperTests(unittest.TestCase):
    def test_input_values_strips_counts_and_pairs_labels(self):
        prop = {"x-enum-labels": ["Volvo ( 20 332 )", "Saab"], "anyOf": [{"type": "string", "enum": ["0.818", "0.2"]}, {"type": "number", "enum": [0.818, 0.2]}]}
        self.assertEqual(input_values(prop), {"Volvo": "0.818", "Saab": "0.2"})

    def test_clean_text(self):
        self.assertEqual(clean_text("a\x00\n  b\t"), "a b")
        self.assertEqual(clean_text("x" * 300, 10), "xxxxxxxxx...")


if __name__ == "__main__":
    unittest.main()
