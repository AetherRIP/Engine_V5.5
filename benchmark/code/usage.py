"""Request ledger, cost calculator and aggregate accounting.

One JSONL row per provider request, including retries and failures.  Probe
requests are written with ``purpose=probe`` and excluded from benchmark totals
by every aggregate; they are still visible so nothing is hidden.

Numbers the provider reported and numbers this project estimated are kept in
separate fields.  A missing count stays ``None`` rather than becoming zero.
"""

from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config

#: Fields every row carries.  ``None`` means "not reported", never zero.
REQUIRED_FIELDS = (
    "timestamp", "strategy", "run", "batch", "paper_id", "item_ids", "provider",
    "model", "purpose", "key_label", "pool", "key_validity", "quota_state",
    "finish_reason",
    "network_state", "input_tokens", "output_tokens", "cached_tokens",
    "thoughts_tokens", "total_tokens", "image_tokens", "reported_usage",
    "estimated_usage", "cost_usd", "cost_estimated", "latency_ms", "http_status",
    "error_class", "error_code", "error_message", "retry_after_s", "cooldown_s", "attempt",
    "started_at", "finished_at", "cooldown_wait_s", "escalated", "success",
)


class UsageLedger:
    def __init__(self, path: Path | None = None):
        self.path = path or config.USAGE_LOG_PATH
        self.pricing = config.load_pricing()

    def record(self, **fields) -> dict:
        row = {name: fields.get(name) for name in REQUIRED_FIELDS}
        row.setdefault("timestamp", None)
        row["timestamp"] = row["timestamp"] or datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        row["provider"] = row["provider"] or "google"
        row["paper_id"] = row["paper_id"] or config.PAPER_ID
        if row["input_tokens"] is None and row["output_tokens"] is None:
            row["estimated_usage"] = False
        price = self.pricing.get(str(row["model"] or ""))
        if price and row["input_tokens"] is not None and row["output_tokens"] is not None:
            row["cost_usd"] = price.cost(
                input_tokens=row["input_tokens"], output_tokens=row["output_tokens"],
                cached_tokens=row["cached_tokens"])
            row["cost_estimated"] = False
        else:
            row["cost_usd"] = None
            row["cost_estimated"] = True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")
        return row

    def rows(self) -> list[dict]:
        if not self.path.is_file():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out


def aggregate(rows: list[dict]) -> dict:
    """Aggregate benchmark rows (probe rows must be filtered by the caller)."""
    if not rows:
        return {"requests": 0}
    ok = [row for row in rows if row.get("success")]
    failures = [row for row in rows if not row.get("success")]
    latencies = [row["latency_ms"] for row in ok if isinstance(row.get("latency_ms"), int)]
    costs = [row["cost_usd"] for row in rows if isinstance(row.get("cost_usd"), (int, float))]
    tokens = lambda name: _sum(rows, name)
    return {
        "requests": len(rows),
        "successful_requests": len(ok),
        "failed_requests": len(failures),
        "failure_rate": round(len(failures) / len(rows), 4),
        "retries": sum(max(0, int(row.get("attempt") or 1) - 1) for row in rows),
        "rate_limit_failures": sum(1 for row in rows if row.get("error_class") == "quota"),
        "rate_limit_rate": round(
            sum(1 for row in rows if row.get("error_class") == "quota") / len(rows), 4),
        "cooldown_s_total": (
            round(sum(row["cooldown_s"] for row in rows
                      if isinstance(row.get("cooldown_s"), (int, float))), 1)
            if any(isinstance(row.get("cooldown_s"), (int, float)) for row in rows) else None),
        "cooldown_events": sum(1 for row in rows if isinstance(row.get("cooldown_s"), (int, float))),
        "cooldown_wait_s_total": (
            round(sum(row["cooldown_wait_s"] for row in rows
                      if isinstance(row.get("cooldown_wait_s"), (int, float))), 3)
            if any(isinstance(row.get("cooldown_wait_s"), (int, float)) for row in rows) else None),
        "cooldown_wait_s_max": (
            max(row["cooldown_wait_s"] for row in rows
                if isinstance(row.get("cooldown_wait_s"), (int, float)))
            if any(isinstance(row.get("cooldown_wait_s"), (int, float)) for row in rows) else None),
        "cooldown_wait_rows": sum(1 for row in rows
                                 if isinstance(row.get("cooldown_wait_s"), (int, float))),
        "input_tokens": tokens("input_tokens"),
        "output_tokens": tokens("output_tokens"),
        "cached_tokens": tokens("cached_tokens"),
        "thoughts_tokens": tokens("thoughts_tokens"),
        "total_tokens": tokens("total_tokens"),
        "image_tokens": tokens("image_tokens"),
        "reported_token_rows": sum(1 for row in rows if row.get("reported_usage")),
        "estimated_token_rows": sum(1 for row in rows if row.get("estimated_usage")),
        "cost_usd": round(sum(costs), 8) if costs else None,
        "cost_rows": len(costs),
        "cost_estimated_rows": sum(1 for row in rows if row.get("cost_estimated")),
        "latency_ms_sum": sum(latencies),
        "latency_ms_mean": round(statistics.mean(latencies), 1) if latencies else None,
        "latency_ms_p50": round(statistics.median(latencies), 1) if latencies else None,
        "latency_ms_max": max(latencies) if latencies else None,
        "cache_savings_estimate_usd": cache_savings(rows),
        "keys_used": sorted({row.get("key_label") for row in ok if row.get("key_label")}),
        "pools_used": sorted({row.get("pool") for row in ok if row.get("pool")}),
    }


def cache_savings(rows: list[dict], pricing: dict | None = None) -> float | None:
    """Value of cache hits at the model's input price.

    This is an upper bound on the saving: the provider may bill cached tokens
    at a different rate, which is why it is labelled an estimate.
    """
    pricing = pricing or config.load_pricing()
    total = 0.0
    found = False
    for row in rows:
        cached = row.get("cached_tokens")
        price = pricing.get(str(row.get("model") or ""))
        if not cached or not price or price.input_per_million is None:
            continue
        total += cached / 1_000_000 * price.input_per_million
        found = True
    return round(total, 8) if found else None


def _sum(rows: list[dict], name: str) -> int | None:
    values = [row[name] for row in rows if isinstance(row.get(name), int)]
    return sum(values) if values else None


def group_by(rows: list[dict], *names: str) -> dict:
    grouped: dict = {}
    for row in rows:
        key = tuple(row.get(name) for name in names)
        grouped.setdefault(key, []).append(row)
    return {key: aggregate(group) for key, group in grouped.items()}


def _row_interval(row: dict) -> tuple[float, float] | None:
    if not row.get("timestamp"):
        return None
    end = _parse(row["timestamp"])
    if row.get("started_at"):
        start = _parse(row["started_at"])
    else:
        latency = row.get("latency_ms")
        start = end - (latency / 1000 if isinstance(latency, (int, float)) else 0.0)
    return (min(start, end), end)


def observed_throughput(rows: list[dict]) -> dict:
    """Measured throughput from ledger timestamps and outcomes.

    Historical rows have no start timestamp, so their interval is reconstructed
    from completion time minus provider latency.  New rows carry explicit
    ``started_at``/``finished_at`` and an instrumented ``cooldown_wait_s``.
    Historical suspensions without that field are reported as next-observed-use
    intervals; they are not treated as configured cooldown values.
    """
    rows = [row for row in rows if row.get("purpose") != "probe"]
    if not rows:
        return {"requests": 0, "successes": 0, "suspensions": 0}
    intervals = [(start, end, row) for row in rows
                 for start, end in [_row_interval(row)] if start is not None]
    events = []
    for start, end, _row in intervals:
        events.append((start, 1))
        events.append((end, -1))
    events.sort(key=lambda item: (item[0], item[1]))
    current = peak = 0
    for _stamp, delta in events:
        current += delta
        peak = max(peak, current)
    span = (max(end for _start, end, _row in intervals)
            - min(start for start, _end, _row in intervals)) if intervals else 0.0
    successes = sum(1 for row in rows if row.get("success"))
    quota_rows = [row for row in rows if row.get("error_class") == "quota"]
    cooldown_records = []
    for row in quota_rows:
        stamp = _parse(row["timestamp"]) if row.get("timestamp") else None
        wait = row.get("cooldown_wait_s")
        source = "instrumented" if isinstance(wait, (int, float)) else None
        if not isinstance(wait, (int, float)) and stamp is not None:
            later = [other for other in rows
                     if other.get("key_label") == row.get("key_label")
                     and other.get("timestamp")
                     and _parse(other["timestamp"]) > stamp]
            later.sort(key=lambda other: _parse(other["timestamp"]))
            if later:
                wait = _parse(later[0]["timestamp"]) - stamp
                source = "next_observed_use"
        cooldown_records.append({
            "timestamp": row.get("timestamp"), "key": row.get("key_label"),
            "strategy": row.get("strategy"), "run": row.get("run"),
            "wait_s": round(wait, 3) if isinstance(wait, (int, float)) else None,
            "source": source or "unreconstructable",
            "next_batch": (later[0].get("batch") if source == "next_observed_use" else None),
        })
    # New rows carry the scheduler's measured acquire wait even when the call
    # succeeded or failed for a reason other than 429.  Keep that measurement
    # visible instead of reporting "unavailable" merely because there was no
    # quota event.
    quota_ids = {id(row) for row in quota_rows}
    for row in rows:
        wait = row.get("cooldown_wait_s")
        if not isinstance(wait, (int, float)) or id(row) in quota_ids:
            continue
        cooldown_records.append({
            "timestamp": row.get("timestamp"), "key": row.get("key_label"),
            "strategy": row.get("strategy"), "run": row.get("run"),
            "wait_s": round(wait, 3), "source": "instrumented",
            "next_batch": None,
        })
    measured = [record for record in cooldown_records if record["source"] == "instrumented"]
    next_use = [record for record in cooldown_records if record["source"] == "next_observed_use"]
    return {
        "requests": len(rows),
        "successes": successes,
        "span_s": round(span, 2),
        "requests_per_minute": round(len(rows) / span * 60, 2) if span else None,
        "successes_per_minute": round(successes / span * 60, 2) if span else None,
        "concurrency_peak": peak,
        "concurrency_observed_max": peak,
        "rate_limit_failures": len(quota_rows),
        "rate_limit_rate": round(len(quota_rows) / len(rows), 4) if rows else None,
        "suspensions": len(quota_rows),
        "cooldown_wait_s_total": round(sum(record["wait_s"] for record in measured), 3) if measured else None,
        "cooldown_wait_s_max": max((record["wait_s"] for record in measured), default=None),
        "cooldown_wait_sources": {
            "instrumented": len(measured),
            "next_observed_use": len(next_use),
            "unreconstructable": sum(1 for record in cooldown_records
                                     if record["source"] == "unreconstructable"),
        },
        "cooldown_records": cooldown_records,
    }


def wall_clock(rows: list[dict]) -> dict:
    """Observed request and success rates; not a claim about provider limits."""
    observed = observed_throughput(rows)
    return {"span_s": observed.get("span_s"),
            "requests_per_minute": observed.get("requests_per_minute"),
            "successes_per_minute": observed.get("successes_per_minute")}


def _parse(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()
