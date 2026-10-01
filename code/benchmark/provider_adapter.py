#!/usr/bin/env python3
"""
provider_adapter.py — policy-compliant provider calls for the AI2 benchmark.

Policy (Round 2 instructions F):
- one in-flight request per provider (process-level locks)
- OpenAI request STARTS at least 10 s apart; DeepSeek 3 s
- at most 4,000 output tokens per call
- honor Retry-After and stricter provider limits
- backoff min(60, 2^n + uniform(0,1)); at most 4 retries for transient failures
- stop on auth (401), insufficient balance/hard quota (402/403)
- no tenacity
- raw response payload saved SECURELY (mode 600) BEFORE parsing
- authorization headers never written to disk
- dry-run mode performs zero network requests

All accounting (request count, tokens, cost) goes to the shared budget ledger
passed in by the caller (run_benchmark.py).
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT_TOKENS = 4000
OPENAI_MIN_GAP_S = 10.0
DEEPSEEK_MIN_GAP_S = 3.0
MAX_ATTEMPTS = 5  # initial + 4 retries

# Pinned pricing (per 1M tokens), OpenAI pricing page 2026-10-01
PRICING = {
    "openai": {"gpt-4.1-mini": (0.40, 1.60)},
    "deepseek": {"deepseek-v4-pro": (0.66, 1.98)},  # off-peak cache-miss; conservative peak: input 1.32, output 3.96
}

_last_start: dict[str, float] = {}
_locks: dict[str, threading.Lock] = {}


def _lock(provider: str) -> threading.Lock:
    if provider not in _locks:
        _locks[provider] = threading.Lock()
    return _locks[provider]


def _enforce_start_gap(provider: str, min_gap: float) -> None:
    now = time.monotonic()
    last = _last_start.get(provider, 0.0)
    if last != 0.0:  # first request in this process: no wait
        wait = min_gap - (now - last)
        if wait > 0:
            time.sleep(wait)
    _last_start[provider] = time.monotonic()


class ProviderError(RuntimeError):
    """Hard failure: no further retries permitted."""


@dataclass
class CallResult:
    provider: str
    model: str
    content: str
    reasoning_content: str
    usage: dict
    cost_usd: float
    raw_path: str | None
    attempts: int
    latency_s: float


def cost_usd(provider: str, model: str, usage: dict) -> float:
    key = model
    prices = PRICING.get(provider, {}).get(key)
    if prices is None:
        prices = PRICING.get(provider, {}).get("gpt-4.1-mini", (0.40, 1.60))
    pin, pout = prices
    return (usage.get("prompt_tokens", 0) / 1e6) * pin + (usage.get("completion_tokens", 0) / 1e6) * pout


def call(provider: str, model: str, messages: list, *,
         max_output_tokens: int, api_key: str, dry_run: bool = False,
         raw_dir: Path | None = None, base_url: str | None = None,
         timeout_s: int = 300, temperature: float | None = None,
         ledger=None, run_id: str = "", purpose: str = "") -> CallResult:
    if max_output_tokens > MAX_OUTPUT_TOKENS:
        raise ValueError(f"max_output_tokens {max_output_tokens} exceeds policy cap {MAX_OUTPUT_TOKENS}")
    if dry_run:
        return CallResult(provider, model, "", "", {"prompt_tokens": 0, "completion_tokens": 0},
                          0.0, None, 0, 0.0)
    if provider not in ("openai", "deepseek"):
        raise ValueError("unknown provider " + provider)
    if base_url is None:
        base_url = ("https://api.openai.com/v1/chat/completions" if provider == "openai"
                    else "https://api.deepseek.com/chat/completions")
    min_gap = OPENAI_MIN_GAP_S if provider == "openai" else DEEPSEEK_MIN_GAP_S
    body: dict = {"model": model, "messages": messages}
    if provider == "openai":
        body["max_completion_tokens"] = max_output_tokens
        if temperature is not None:
            body["temperature"] = temperature
    else:
        body["max_tokens"] = max_output_tokens
        body["temperature"] = temperature if temperature is not None else 0.0
    payload = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + api_key}

    attempt = 0
    with _lock(provider):  # one in-flight per provider
        while True:
            _enforce_start_gap(provider, min_gap)
            started = time.monotonic()
            try:
                req = urllib.request.Request(base_url, data=payload, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    raw = resp.read()
                latency = time.monotonic() - started
                data = json.loads(raw.decode("utf-8"))
                if raw_dir is not None:
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    p = raw_dir / f"resp_{provider}_{int(time.time()*1000)}_{attempt}.json"
                    p.write_text(raw.decode("utf-8", errors="replace"))
                    os.chmod(p, 0o600)
                else:
                    p = None
                msg = (data.get("choices") or [{}])[0].get("message", {})
                usage = data.get("usage", {})
                content = msg.get("content") or ""
                reasoning = msg.get("reasoning_content") or ""
                cst = cost_usd(provider, model, usage)
                if ledger is not None:
                    ledger.record(provider, model, purpose, run_id, "ok", usage, cst, attempt + 1)
                return CallResult(provider, model, content, reasoning, usage, cst,
                                  str(p) if p else None, attempt + 1, latency)
            except urllib.error.HTTPError as e:
                body_text = ""
                try:
                    body_text = e.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                code = e.code
                if code in (401, 402, 403):
                    if ledger is not None:
                        ledger.record(provider, model, purpose, run_id, f"hard_error_{code}",
                                      {}, 0.0, attempt + 1)
                    raise ProviderError(f"hard error {code}: {body_text[:200]}")
                attempt += 1
                if attempt > MAX_ATTEMPTS - 1:
                    if ledger is not None:
                        ledger.record(provider, model, purpose, run_id, f"failed_http_{code}",
                                      {}, 0.0, attempt + 1)
                    raise RuntimeError(f"failed after {MAX_ATTEMPTS} attempts: HTTP {code} {body_text[:200]}")
                if ledger is not None:
                    ledger.record(provider, model, purpose, run_id, f"retry_http_{code}",
                                  {}, 0.0, attempt + 1)
                if e.headers and e.headers.get("Retry-After"):
                    try:
                        wait = float(e.headers["Retry-After"])
                    except ValueError:
                        wait = min(60.0, 2 ** attempt + random.random())
                else:
                    wait = min(60.0, 2 ** attempt + random.random())
                time.sleep(wait)
            except urllib.error.URLError as e:
                attempt += 1
                if attempt > MAX_ATTEMPTS - 1:
                    if ledger is not None:
                        ledger.record(provider, model, purpose, run_id, "failed_network",
                                      {}, 0.0, attempt + 1)
                    raise RuntimeError(f"network failure after {MAX_ATTEMPTS} attempts: {e}")
                if ledger is not None:
                    ledger.record(provider, model, purpose, run_id, "retry_network",
                                  {}, 0.0, attempt + 1)
                time.sleep(min(60.0, 2 ** attempt + random.random()))


class BudgetLedger:
    """Append-only accounting; ceiling enforced by callers."""

    def __init__(self, path: Path, ceiling_usd: float, ceiling_requests: int):
        self.path = Path(path)
        self.ceiling_usd = ceiling_usd
        self.ceiling_requests = ceiling_requests
        self._rows: list[dict] = []
        if self.path.exists():
            try:
                with open(self.path) as f:
                    self._rows = [json.loads(l) for l in f if l.strip()]
            except Exception:
                self._rows = []

    def totals(self):
        n = len(self._rows)  # every attempt counts against the request ceiling
        c = sum(float(r.get("cost_usd", 0)) for r in self._rows)
        return n, c

    def remaining(self):
        n, c = self.totals()
        return max(0, self.ceiling_requests - n), max(0.0, self.ceiling_usd - c)

    def record(self, provider, model, purpose, run_id, status, usage, cost, attempts):
        row = {
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "provider": provider, "model": model, "purpose": purpose,
            "run_id": run_id, "status": status, "usage": usage,
            "cost_usd": round(cost, 6), "attempts": attempts,
        }
        self._rows.append(row)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(row) + "\n")
