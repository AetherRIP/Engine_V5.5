"""Request execution: model selection, retries, key scheduling and logging.

Every provider call goes through :class:`Executor`.  That is the only place a
key is touched, the only place a retry happens, and the only place a ledger row
is written, so "how many requests did this strategy make" has one answer.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config
from .provider import GeminiClient, ProviderResult


@dataclass
class ModelSelection:
    primary: str
    lite: str | None
    strong: str | None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"primary": self.primary, "lite": self.lite, "strong": self.strong,
                "notes": self.notes}


def select_models(client: GeminiClient, pool, ledger,
                  *, primary_candidates: list[str] | None = None) -> ModelSelection:
    """Verify role candidates with minimal real generations.

    A candidate is only accepted after a successful request.  Probes are tried
    on up to three healthy keys, because a transient 503 or a per-key quota on
    the first key says nothing about the model.  Every probe is logged with
    ``purpose=probe``.
    """
    healthy = [record for record in pool.keys
               if record.key_validity == "VALID" and record.probe_state == "healthy"]
    if not healthy:
        healthy = [record for record in pool.keys if record.key_validity == "VALID"]
    if not healthy:
        raise RuntimeError("no valid key to verify models with")
    trial_keys = healthy[:3]
    notes: list[str] = []

    def log_probe(key, model, result):
        ledger.record(
            strategy="probe", run=0, batch="model-verification", item_ids=[],
            model=model, purpose="probe", key_label=key.label, pool=key.pool,
            key_validity=key.key_validity, quota_state=key.quota_state,
            finish_reason=result.finish_reason,
            network_state=key.network_state,
            input_tokens=result.usage.get("input_tokens"),
            output_tokens=result.usage.get("output_tokens"),
            cached_tokens=result.usage.get("cached_tokens"),
            thoughts_tokens=result.usage.get("thoughts_tokens"),
            total_tokens=result.usage.get("total_tokens"),
            image_tokens=result.usage.get("image_tokens"),
            reported_usage=bool(result.usage.get("reported")), estimated_usage=False,
            latency_ms=result.latency_ms, http_status=result.http_status,
            error_class="" if result.ok else result.status,
            error_code=result.error_code, error_message=result.error_message,
            retry_after_s=result.retry_after_s, cooldown_s=None, attempt=1,
            escalated=False, success=result.ok)

    candidates = dict(config.MODEL_CANDIDATES)
    if primary_candidates:
        candidates["primary"] = list(primary_candidates)

    def first_working(role: str) -> str | None:
        for model in candidates.get(role, []):
            for key in trial_keys:
                result = client.probe_generate(key.secret, model=model)
                log_probe(key, model, result)
                if result.ok:
                    notes.append(f"{role}: {model} verified on {key.label}")
                    return model
                if result.status == "network":
                    break
            notes.append(f"{role}: {model} not verified on the first "
                         f"{len(trial_keys)} healthy key(s)")
        return None

    primary = first_working("primary") or config.PRIMARY_MODEL
    lite = first_working("lite")
    strong = first_working("strong")
    if lite is None:
        notes.append("lite: no Lite model verified; strategy C must be reported as blocked")
    if strong is None:
        notes.append("strong: no stronger model verified; escalation uses the primary model")
        strong = primary
    return ModelSelection(primary=primary, lite=lite, strong=strong, notes=notes)


class Executor:
    def __init__(self, client: GeminiClient, pool, ledger):
        self.client = client
        self.pool = pool
        self.ledger = ledger

    def call(self, *, strategy: str, run: int, batch: str, purpose: str,
             model: str, parts: list[dict], system: str, schema: dict,
             item_ids: list[str], escalated: bool = False,
             max_attempts: int = 4) -> tuple[ProviderResult, list[dict]]:
        attempts: list[dict] = []
        last: ProviderResult | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                acquire_started = time.monotonic()
                key = self.pool.acquire(purpose=purpose)
                cooldown_wait_s = round(max(0.0, time.monotonic() - acquire_started), 3)
            except Exception as error:  # noqa: BLE001 — reported, not hidden
                last = ProviderResult(status="no_key", error_code=type(error).__name__,
                                      error_message=str(error)[:300])
                attempts.append({"attempt": attempt, "status": "no_key", "error": str(error)[:300]})
                break
            started = time.monotonic()
            started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            result = self.client.generate(
                key.secret, model=model, parts=parts, system=system, schema=schema,
                thinking_budget=config.thinking_budget_for(model))
            finished_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            if result.ok:
                self.pool.mark_success(key, benchmark=True)
            elif result.status == "quota":
                cooldown = self.pool.mark_rate_limited(
                    key, retry_after=result.retry_after_s, quota_id=result.quota_id,
                    daily=result.daily_quota)
                attempts.append({"attempt": attempt, "status": "quota",
                                 "cooldown_s": cooldown, "key": key.label})
            elif result.status == "invalid":
                self.pool.mark_invalid(key, result.error_code)
                attempts.append({"attempt": attempt, "status": "invalid", "key": key.label})
            elif result.status == "network":
                self.pool.mark_network_failure(key, result.error_code)
                attempts.append({"attempt": attempt, "status": "network", "key": key.label})
            else:
                self.pool.mark_other_failure(key, result.error_code)
                attempts.append({"attempt": attempt, "status": result.status, "key": key.label})

            self.ledger.record(
                strategy=strategy, run=run, batch=batch, item_ids=item_ids,
                model=model, purpose=purpose, key_label=key.label, pool=key.pool,
                key_validity=key.key_validity, quota_state=key.quota_state,
                finish_reason=result.finish_reason,
                network_state=key.network_state,
                input_tokens=result.usage.get("input_tokens"),
                output_tokens=result.usage.get("output_tokens"),
                cached_tokens=result.usage.get("cached_tokens"),
                thoughts_tokens=result.usage.get("thoughts_tokens"),
                total_tokens=result.usage.get("total_tokens"),
                image_tokens=result.usage.get("image_tokens"),
                reported_usage=bool(result.usage.get("reported")),
                estimated_usage=bool(result.ok and not result.usage.get("reported")),
                latency_ms=result.latency_ms or int((time.monotonic() - started) * 1000),
                http_status=result.http_status, error_class=result.status if not result.ok else "",
                error_code=result.error_code, error_message=result.error_message,
                retry_after_s=result.retry_after_s,
                cooldown_s=attempts[-1].get("cooldown_s") if attempts else None,
                started_at=started_at, finished_at=finished_at,
                cooldown_wait_s=cooldown_wait_s,
                attempt=attempt, escalated=escalated, success=result.ok,
            )
            last = result
            if result.ok:
                break
            if result.status in {"model_unavailable", "no_key"}:
                break
            if result.status == "invalid" and attempt == max_attempts:
                break
            time.sleep(min(4.0, 0.75 * (2 ** (attempt - 1))))
        return last or ProviderResult(status="no_attempt"), attempts


def parse_json(text: str) -> tuple[dict | None, str]:
    """Parse a model response, tolerating a fenced code block only."""
    value = (text or "").strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[-1]
        if value.rstrip().endswith("```"):
            value = value.rstrip()[:-3]
    try:
        parsed = json.loads(value)
    except ValueError as error:
        return None, f"invalid JSON: {error}"
    if not isinstance(parsed, dict):
        return None, "JSON root is not an object"
    return parsed, ""
