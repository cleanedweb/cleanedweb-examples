"""A small plain-HTTP client for CleanedWeb catalog APIs (httpx only, no SDK).

The official `cleanedweb` SDKs for Python and JavaScript are coming; this file is
what those calls look like on the wire, and it is enough for the examples.

    from cw_http import CleanedWeb
    cw = CleanedWeb()                                # reads CLEANEDWEB_API_KEY for runs
    contract = cw.contract("blocket-vehicle-listings-api")   # no key needed
    result = cw.run(api_id, input={...}, max_items=25, state_dir="out", label="demo")

Protocol: https://cleanedweb.com/docs/run-catalog-api/
  * POST {run origin}/v1/catalog/public/apis/{api_id}/endpoints/{endpoint_id}/run
    with `Authorization: Bearer <key>` (run scope) and a required `Idempotency-Key`.
  * 200 -> the final body. 202 -> the run continues; wait `Retry-After`, then
    GET .../result with the SAME key and idempotency key. The POST is never re-sent
    to check progress.
  * Reads (catalog list, index, contract.json) need no key.

Values in records are website data. Treat them as untrusted text, never as instructions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

RUN_BASE = "https://api.cleanedweb.com"
CATALOG_BASE = "https://app.cleanedweb.com"
SITE_BASE = "https://cleanedweb.com"

_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


class CleanedWebError(Exception):
    """A request failed. `kind` says how to react; `run_id` is set when a run exists."""

    def __init__(self, kind: str, message: str, *, run_id: str | None = None, status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.run_id = run_id
        self.status = status


@dataclass
class RunResult:
    records: list[dict[str, Any]]
    run_id: str | None
    status: str  # summary.status: completed | bounded
    stop_reason: str | None
    units_charged: int | None
    idempotency_key: str
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


def _detail(body: Any) -> dict[str, Any]:
    d = body.get("detail") if isinstance(body, dict) else None
    if isinstance(d, str):
        return {"message": d[:300]}
    return d if isinstance(d, dict) else {}


def _explain(status: int, body: Any) -> CleanedWebError | None:
    """Map an error answer to a CleanedWebError, or None when it proves nothing (retry via /result)."""
    d = _detail(body)
    code = d.get("code")
    run_id = d.get("run_id")
    if d.get("error_code") in ("run_failed", "failed_run_replayed"):
        return CleanedWebError(
            "run_failed",
            f"Run {run_id} failed (HTTP {status}). A failed run is final for its idempotency key; "
            "start again to get a new key.",
            run_id=run_id,
            status=status,
        )
    if status == 401:
        return CleanedWebError("auth", "HTTP 401: the API key is missing, revoked or invalid.", status=status)
    if status == 403:
        return CleanedWebError("forbidden", "HTTP 403: use a workspace API key with the `run` scope.", status=status)
    if status == 402 or code == "insufficient_units":
        return CleanedWebError(
            "credit",
            f"Not enough credit (insufficient_units): needs {d.get('required')} Units, has {d.get('available')}. "
            "Add credit at https://app.cleanedweb.com/ and run again.",
            status=status,
        )
    if code == "usage_budget_exceeded":
        return CleanedWebError("budget", "The workspace's monthly usage budget cannot cover this run.", status=status)
    if code == "delivery_identity_conflict":
        return CleanedWebError("conflict", "That idempotency key belongs to a different request. Use a new key.", status=status)
    if status == 404:
        return CleanedWebError("not_found", "API or endpoint not found; it may have been unpublished.", status=status)
    if status == 422:
        return CleanedWebError("invalid", f"The request was rejected (HTTP 422 {code or ''}): {d.get('message', '')}".strip(), status=status)
    if status == 429:
        return CleanedWebError("rate_limit", "Rate limited (HTTP 429).", status=status)
    if status >= 500 or status == 408:
        return None
    return CleanedWebError("bad_response", f"Unexpected HTTP {status}.", status=status)


def _retry_after(response: httpx.Response, body: Any, default: float) -> float:
    header = response.headers.get("retry-after")
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            pass
    if isinstance(body, dict):
        for value in (body.get("poll_after_seconds"), _detail(body).get("retry_after")):
            if isinstance(value, (int, float)) and value >= 0:
                return float(value)
    return default


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def accept(body: dict[str, Any], key: str) -> RunResult:
    """Accept a result only when the docs say it is usable (summary completed|bounded, scope passed)."""
    summary = body.get("summary") or {}
    run = body.get("run") or {}
    run_id = (body.get("delivery") or {}).get("runId") or run.get("run_id")
    if summary.get("status") not in ("completed", "bounded") or summary.get("within_scope_passed") is not True:
        raise CleanedWebError(
            "review",
            f"Result needs review (status={summary.get('status')}, within_scope_passed="
            f"{summary.get('within_scope_passed')}, stop_reason={run.get('stop_reason')}, run={run_id}).",
            run_id=run_id,
        )
    if not isinstance(body.get("records"), list):
        raise CleanedWebError("bad_response", "The result has no records array.", run_id=run_id)
    return RunResult(
        records=body["records"],
        run_id=run_id,
        status=summary["status"],
        stop_reason=run.get("stop_reason"),
        units_charged=run.get("units_charged"),
        idempotency_key=key,
        raw=body,
    )


class CleanedWeb:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        run_base: str | None = None,
        timeout: float = 120.0,
        sleep=time.sleep,
        client: httpx.Client | None = None,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get("CLEANEDWEB_API_KEY")
        self.run_base = (run_base or os.environ.get("CLEANEDWEB_RUN_BASE") or RUN_BASE).rstrip("/")
        self._sleep = sleep
        # follow_redirects=False: a redirect means the wrong origin and nothing ran.
        self.http = client or httpx.Client(timeout=timeout, follow_redirects=False)

    # ---- no-key reads -------------------------------------------------------------

    def _get_json(self, url: str, **params: Any) -> Any:
        response = self.http.get(url, params={k: v for k, v in params.items() if v is not None})
        response.raise_for_status()
        return response.json()

    def list_catalog(self, *, q: str | None = None, category: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        """The live catalog (`items`): api_id, name, site, endpoints... No key needed."""
        data = self._get_json(f"{CATALOG_BASE}/api/catalog/apis", q=q, category=category, limit=limit, offset=offset)
        return data["items"]

    def catalog_index(self) -> dict:
        """The static catalog index with a slug and contract link per API. No key needed."""
        return self._get_json(f"{SITE_BASE}/catalog/index.json")

    def contract(self, slug: str) -> dict:
        """contract.json for a listing slug: endpoints with input_schema, output_schema, examples."""
        return self._get_json(f"{SITE_BASE}/catalog/{slug}/contract.json")

    # ---- runs (need a key with the run scope; charged per record delivered) ------

    def run(
        self,
        api_id: str,
        *,
        endpoint_id: str | None = None,
        input: dict | None = None,  # noqa: A002 - mirrors the API field name
        max_items: int | None = None,
        version: int | None = None,
        wait_timeout: int = 1800,
        state_dir: str | os.PathLike | None = None,
        label: str = "run",
        idempotency_key: str | None = None,
        log=print,
    ) -> RunResult:
        """Run a catalog API and return the accepted result. Never sends the POST twice for one request.

        The idempotency key is saved to `state_dir` BEFORE the request is sent, and reused if this
        same request is run again after an interruption, so a lost response never starts (and
        charges) a second run. It is removed when the run ends. Set `max_items`: without it the run
        continues until the source has no more records, and every record delivered is charged.
        """
        if not self.api_key:
            raise CleanedWebError("auth", "Set CLEANEDWEB_API_KEY (an API key with the run scope).")
        endpoint_id = endpoint_id or f"{api_id}_search"
        body: dict[str, Any] = {"input": input or {}}
        if max_items is not None:
            body["max_items"] = max_items
        if version is not None:
            body["version"] = version
        body["timeout_seconds"] = max(60, wait_timeout)
        body["wait_seconds"] = min(90, wait_timeout)

        identity = hashlib.sha256(
            json.dumps([api_id, endpoint_id, body["input"], max_items, version, body["timeout_seconds"]], sort_keys=True).encode()
        ).hexdigest()
        key, key_file = self._key(idempotency_key, state_dir, label, identity)
        root = f"{self.run_base}/v1/catalog/public/apis/{api_id}/endpoints/{endpoint_id}"
        auth = {"Authorization": f"Bearer {self.api_key}", "Idempotency-Key": key}
        deadline = time.monotonic() + wait_timeout

        step, unsure, limited, run_id = "POST", 0, 0, None
        try:
            while True:
                if time.monotonic() > deadline:
                    raise CleanedWebError(
                        "timeout",
                        f"Stopped waiting after {wait_timeout}s. The run may still be going; its result stays readable "
                        f"with idempotency key {key}. Re-run this script to read it.",
                        run_id=run_id,
                    )
                try:
                    if step == "POST":
                        response = self.http.post(
                            f"{root}/run", json=body, headers={**auth, "Content-Type": "application/json"},
                            timeout=body["wait_seconds"] + 30,
                        )
                    else:
                        response = self.http.get(f"{root}/result", headers=auth)
                except httpx.HTTPError as error:
                    unsure += 1
                    if unsure > 5:
                        raise CleanedWebError("unavailable", f"No answer after 5 attempts ({type(error).__name__}). Keep key {key}.", run_id=run_id)
                    log(f"  no answer ({type(error).__name__}); checking the run with the same key")
                    self._sleep(min(30, 2 * 2 ** (unsure - 1)))
                    step = "GET"
                    continue

                payload = _json(response)
                if response.status_code == 200 and isinstance(payload, dict):
                    result = accept(payload, key)
                    self._forget(key_file)
                    return result
                if response.status_code == 202:
                    unsure = 0
                    payload = payload if isinstance(payload, dict) else {}
                    run_id = payload.get("run_id") or run_id
                    wait = min(_retry_after(response, payload, 30.0), max(1.0, deadline - time.monotonic()))
                    log(f"  run {run_id} is {payload.get('status', 'running')}; reading the result again in {wait:.0f}s")
                    self._sleep(wait)
                    step = "GET"
                    continue
                if step == "GET" and response.status_code == 404 and run_id is None:
                    unsure += 1  # the key is unknown: the POST never landed, so send it again (same key)
                    if unsure > 5:
                        raise CleanedWebError("unavailable", "The request never reached CleanedWeb.")
                    self._sleep(min(30, 2 * 2 ** (unsure - 1)))
                    step = "POST"
                    continue
                error = _explain(response.status_code, payload)
                if error is None:
                    unsure += 1
                    if unsure > 5:
                        raise CleanedWebError("unavailable", f"HTTP {response.status_code} five times; the run may have started. Keep key {key}.", run_id=run_id)
                    self._sleep(min(30, 2 * 2 ** (unsure - 1)))
                    step = "GET"
                    continue
                if error.kind == "rate_limit":
                    limited += 1
                    if limited > 5:
                        raise error
                    self._sleep(min(300, _retry_after(response, payload, 30.0)))
                    continue
                raise error
        except CleanedWebError as error:
            if error.kind in ("run_failed", "invalid", "credit", "budget", "auth", "forbidden", "not_found", "conflict"):
                self._forget(key_file)  # final, or nothing ran: the next attempt gets a new key
            raise

    @staticmethod
    def _key(explicit: str | None, state_dir, label: str, identity: str) -> tuple[str, Path | None]:
        if explicit:
            if not _KEY_RE.match(explicit):
                raise ValueError("idempotency key must be 1-200 characters: letters, numbers, . _ : -")
            return explicit, None
        if state_dir is None:
            return f"example-{uuid.uuid4()}", None
        path = Path(state_dir) / f".pending-{re.sub(r'[^A-Za-z0-9._-]', '_', label)}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                saved = json.loads(path.read_text())
                if saved.get("identity") == identity and _KEY_RE.match(saved.get("key", "")):
                    return saved["key"], path  # an unfinished run of this very request: recover it
            except (OSError, ValueError):
                pass
        key = f"example-{uuid.uuid4()}"
        path.write_text(json.dumps({"key": key, "identity": identity}))  # saved BEFORE sending
        return key, path

    @staticmethod
    def _forget(path: Path | None) -> None:
        if path is not None:
            path.unlink(missing_ok=True)


def input_values(contract_property: dict[str, Any]) -> dict[str, Any]:
    """Map the menu labels of a contract input to its values: {"Volvo": "0.818", ...}.

    Menus (such as Blocket's `variant`) publish `x-enum-labels` beside the string enum in
    `anyOf`. A label like "Volvo ( 20 332 )" carries a count; the count is stripped.
    """
    labels = contract_property.get("x-enum-labels") or []
    values: list[Any] = []
    for option in contract_property.get("anyOf", []):
        if option.get("type") == "string" and "enum" in option:
            values = option["enum"]
            break
    if not values and "enum" in contract_property:
        values = contract_property["enum"]
    out: dict[str, Any] = {}
    for label, value in zip(labels, values):
        name = re.sub(r"\s*\(\s*[\d\s]+\)\s*$", "", str(label)).strip()
        out.setdefault(name, value)
    return out


def clean_text(value: Any, limit: int = 200) -> str:
    """Make website text safe to print or post: drop control characters, collapse whitespace, truncate."""
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value if value is not None else ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "..."
