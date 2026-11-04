"""Central API-key pool: independent validity, quota and network state.

Rules implemented here:

* keys are read once and only ever exposed by positional label;
* a 429 never marks a key invalid, and an invalid key is never described as
  merely rate-limited;
* a rate-limited key is suspended for the provider's stated retry window (or a
  conservative default) and is not retried in a loop;
* the scheduler round-robins over eligible keys so one key is not exhausted
  while another eligible key sits idle;
* observed quota pools are recorded, never invented.  Distribution across keys
  is load balancing, not additional quota.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config

MINUTE_COOLDOWN = 60.0
DAILY_COOLDOWN = 24 * 3600.0
OBSERVATION_WINDOW = 120.0


@dataclass
class KeyRecord:
    label: str
    secret: str = field(repr=False)
    key_validity: str = "UNKNOWN"       # VALID / INVALID / UNKNOWN
    quota_state: str = "UNKNOWN"        # AVAILABLE / RATE_LIMITED / QUOTA_EXHAUSTED / UNKNOWN
    network_state: str = "UNKNOWN"      # REACHABLE / UNREACHABLE / UNKNOWN
    pool: str = "POOL_UNKNOWN"
    cooldown_until: float = 0.0
    cooldown_kind: str = ""
    last_error_code: str = ""
    last_quota_id: str = ""
    requests: int = 0
    successes: int = 0
    failures: int = 0
    rate_limit_hits: int = 0
    benchmark_successes: int = 0
    probe_state: str = "not_probed"

    def available(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        if self.quota_state == "QUOTA_EXHAUSTED":
            # A daily quota is parked for a reset window, not forever.  Only a
            # key parked by a daily 429 carries cooldown_kind="daily"; a key
            # exhausted at discovery keeps the explicit exclusion.
            if self.cooldown_kind == "daily" and self.cooldown_until <= now:
                self.quota_state = "UNKNOWN"
                self.cooldown_kind = ""
                if self.probe_state == "quota_limited":
                    self.probe_state = "healthy"
            else:
                return False
        probe_usable = (self.probe_state in {"healthy", "not_probed"}
                        or self.successes > 0)
        return (self.key_validity == "VALID"
                and self.network_state != "UNREACHABLE"
                and probe_usable
                and self.cooldown_until <= now)

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "key_validity": self.key_validity,
            "quota_state": self.quota_state,
            "network_state": self.network_state,
            "pool": self.pool,
            "cooldown_remaining_s": max(0, round(self.cooldown_until - time.time())),
            "cooldown_kind": self.cooldown_kind,
            "last_error_code": self.last_error_code,
            "last_quota_id": self.last_quota_id,
            "requests": self.requests,
            "successes": self.successes,
            "failures": self.failures,
            "rate_limit_hits": self.rate_limit_hits,
            "benchmark_successes": self.benchmark_successes,
            "probe_state": self.probe_state,
        }


class NoEligibleKey(RuntimeError):
    """Every key is invalid, unreachable, or cooling down."""


class KeyPool:
    def __init__(self, secrets: list[str], state_path: Path | None = None):
        if not secrets:
            raise ValueError("the authorised key pool is empty")
        self.keys = [KeyRecord(label=f"KEY_{index:02d}", secret=value)
                     for index, value in enumerate(secrets, start=1)]
        self.state_path = state_path or config.KEY_STATE_PATH
        self._cursor = 0
        self._pool_serial = 0
        self._last_rate_limited: tuple[str, float, str] | None = None
        self.events: list[dict] = []

    @classmethod
    def from_state(cls, secrets: list[str], state_path: Path | None = None) -> "KeyPool":
        """Load the historical key counters without probing or touching secrets.

        This is used by the strategy-scoped C rerun: old counters and events are
        preserved, while an expired daily/per-minute cooldown is released.  The
        caller is responsible for providing the same in-memory key list; the
        state file contains labels and counters only.
        """
        path = state_path or config.KEY_STATE_PATH
        pool = cls(secrets, path)
        if not path.is_file():
            return pool
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return pool

        updated = _parse_time(state.get("updated_at"))
        now = time.time()
        elapsed = max(0.0, now - updated) if updated else 0.0
        by_label = {entry.get("label"): entry for entry in state.get("keys", [])
                    if isinstance(entry, dict)}
        for record in pool.keys:
            entry = by_label.get(record.label)
            if not entry:
                continue
            for field_name in ("key_validity", "quota_state", "network_state", "pool",
                               "last_error_code", "last_quota_id", "probe_state"):
                if entry.get(field_name) is not None:
                    setattr(record, field_name, entry[field_name])
            for field_name in ("requests", "successes", "failures", "rate_limit_hits",
                               "benchmark_successes"):
                try:
                    setattr(record, field_name, int(entry.get(field_name, 0) or 0))
                except (TypeError, ValueError):
                    setattr(record, field_name, 0)
            remaining = max(0.0, float(entry.get("cooldown_remaining_s") or 0.0))
            left = max(0.0, remaining - elapsed)
            kind = entry.get("cooldown_kind") or (
                "daily" if record.quota_state == "QUOTA_EXHAUSTED" else "")
            record.cooldown_until = now + left if left > 0 else 0.0
            record.cooldown_kind = kind if left > 0 else ""
            if left <= 0 and record.quota_state == "QUOTA_EXHAUSTED":
                # A healthy key parked by a daily quota is usable after its
                # window.  Discovery-limited keys remain excluded by probe_state.
                if record.probe_state == "healthy" or kind == "daily":
                    record.quota_state = "UNKNOWN"
                    record.cooldown_kind = ""
                    if record.probe_state == "quota_limited":
                        record.probe_state = "healthy"
        pool.events = list(state.get("events", []))
        return pool

    # -- discovery ---------------------------------------------------------

    def probe(self, client) -> list[dict]:
        """Probe every key: model listing plus one minimal generation.

        Probe usage is deliberately returned separately; the caller logs it with
        ``purpose=probe`` so it never inflates benchmark totals.
        """
        results = []
        for record in self.keys:
            listing = client.list_models(record.secret)
            probe = {"label": record.label, "models_list": listing["status"],
                     "generate": None}
            if listing["status"] == "ok":
                record.key_validity = "VALID"
                record.network_state = "REACHABLE"
                record.pool = f"POOL_UNKNOWN_{record.label}"
            elif listing["status"] == "invalid":
                record.key_validity = "INVALID"
                record.network_state = "REACHABLE"
                record.last_error_code = listing["error_code"]
                record.pool = f"POOL_EXCLUDED_{record.label}"
                record.probe_state = "invalid_key"
                results.append(probe)
                continue
            elif listing["status"] == "quota":
                # A quota response proves the key is authentic and reachable.
                record.key_validity = "VALID"
                record.network_state = "REACHABLE"
                record.quota_state = _quota_state(listing)
                record.last_error_code = listing["error_code"]
                record.last_quota_id = listing.get("quota_id", "")
                record.pool = f"POOL_UNKNOWN_{record.label}"
                record.probe_state = "quota_limited"
                record.cooldown_kind = ("daily" if record.quota_state == "QUOTA_EXHAUSTED"
                                        else "per_minute")
                record.cooldown_until = time.time() + (
                    DAILY_COOLDOWN if record.quota_state == "QUOTA_EXHAUSTED"
                    else MINUTE_COOLDOWN)
                results.append(probe)
                continue
            elif listing["status"] == "network":
                record.key_validity = "UNKNOWN"
                record.network_state = "UNREACHABLE"
                record.last_error_code = listing["error_code"]
                record.probe_state = "network_failed"
                results.append(probe)
                continue

            if record.key_validity == "VALID":
                gen = client.probe_generate(record.secret)
                probe["generate"] = {
                    "status": gen.status,
                    "http_status": gen.http_status,
                    "error_code": gen.error_code,
                    "model": gen.model,
                    "usage": gen.usage,
                    "latency_ms": gen.latency_ms,
                }
                if gen.ok:
                    record.quota_state = "AVAILABLE"
                    record.probe_state = "healthy"
                    record.successes += 1
                elif gen.status == "quota":
                    record.quota_state = "QUOTA_EXHAUSTED" if gen.daily_quota else "RATE_LIMITED"
                    record.last_quota_id = gen.quota_id
                    record.rate_limit_hits += 1
                    record.probe_state = "quota_limited"
                    record.cooldown_kind = ("daily" if gen.daily_quota else "per_minute")
                    record.cooldown_until = time.time() + (
                        DAILY_COOLDOWN if gen.daily_quota else MINUTE_COOLDOWN)
                elif gen.status == "invalid":
                    record.key_validity = "INVALID"
                    record.last_error_code = gen.error_code
                    record.probe_state = "invalid_key"
                elif gen.status == "network":
                    record.network_state = "UNREACHABLE"
                    record.probe_state = "network_failed"
                else:
                    record.probe_state = gen.status
                record.requests += 1
            results.append(probe)
        self._infer_pools()
        self._save()
        return results

    # -- scheduling --------------------------------------------------------

    def acquire(self, max_wait: float = 90.0, purpose: str = "generate") -> KeyRecord:
        """Return the next eligible key in round-robin order.

        If every key is cooling, wait up to ``max_wait`` for the earliest one;
        never spin on a rate-limited key.
        """
        deadline = time.time() + max_wait
        while True:
            eligible = [record for record in self.keys if record.available()]
            if eligible:
                break
            now = time.time()
            future = [record.cooldown_until for record in self.keys
                      if record.key_validity == "VALID" and record.cooldown_until > now]
            if not future or now >= deadline:
                raise NoEligibleKey(_no_key_reason(self.keys))
            time.sleep(min(5.0, max(0.5, min(future) - now)))
        record = eligible[self._cursor % len(eligible)]
        self._cursor += 1
        return record

    def mark_success(self, record: KeyRecord, *, benchmark: bool) -> None:
        record.requests += 1
        record.successes += 1
        record.failures = max(0, record.failures)
        if record.quota_state in {"RATE_LIMITED", "UNKNOWN"}:
            record.quota_state = "AVAILABLE"
        if record.network_state in {"UNKNOWN", "UNREACHABLE"}:
            record.network_state = "REACHABLE"
        record.cooldown_until = 0.0
        record.cooldown_kind = ""
        if benchmark:
            record.benchmark_successes += 1
        if self._last_rate_limited:
            other_label, when, quota_id = self._last_rate_limited
            if other_label != record.label and time.time() - when <= OBSERVATION_WINDOW:
                self._observe_independence(record, other_label, quota_id)
        self._save()

    def mark_rate_limited(self, record: KeyRecord, *, retry_after: float | None,
                          quota_id: str, daily: bool) -> float:
        record.requests += 1
        record.failures += 1
        record.rate_limit_hits += 1
        record.last_quota_id = quota_id
        record.last_error_code = "RESOURCE_EXHAUSTED"
        record.quota_state = "QUOTA_EXHAUSTED" if daily else "RATE_LIMITED"
        if daily:
            cooldown = max(retry_after or 0.0, DAILY_COOLDOWN)
        else:
            cooldown = retry_after if retry_after and retry_after > 0 else MINUTE_COOLDOWN
        record.cooldown_until = time.time() + cooldown
        record.cooldown_kind = "daily" if daily else "per_minute"
        if quota_id and not record.pool.startswith(("POOL_SHARED_", "POOL_OBSERVED_")):
            self._infer_pools()
        self._apply_pool_cooldown(record, cooldown, daily)
        self._last_rate_limited = (record.label, time.time(), quota_id)
        self.events.append({"at": _now(), "event": "rate_limited", "key": record.label,
                            "quota_id": quota_id, "cooldown_s": cooldown,
                            "kind": record.cooldown_kind})
        self._save()
        return cooldown

    def mark_invalid(self, record: KeyRecord, error_code: str) -> None:
        record.requests += 1
        record.failures += 1
        record.key_validity = "INVALID"
        record.last_error_code = error_code
        record.pool = f"POOL_EXCLUDED_{record.label}"
        record.cooldown_until = float("inf")
        self.events.append({"at": _now(), "event": "invalid_key", "key": record.label,
                            "error_code": error_code})

    def mark_network_failure(self, record: KeyRecord, error_code: str) -> None:
        record.requests += 1
        record.failures += 1
        record.network_state = "UNREACHABLE"
        record.last_error_code = error_code
        record.cooldown_until = time.time() + 30

    def mark_other_failure(self, record: KeyRecord, error_code: str) -> None:
        record.requests += 1
        record.failures += 1
        record.last_error_code = error_code
        if error_code in {"PERMISSION_DENIED", "FAILED_PRECONDITION"}:
            # The key authenticates but this project may not generate with the
            # model.  Keep key_validity VALID (it is not revoked) and exclude it
            # from scheduling for the rest of the experiment.
            record.probe_state = "generation_denied"
            record.cooldown_until = float("inf")

    # -- observed pools ----------------------------------------------------

    def _apply_pool_cooldown(self, record: KeyRecord, cooldown: float, daily: bool) -> None:
        """Suspend other keys already inferred to share this key's quota pool."""
        if not record.pool.startswith(("POOL_SHARED_", "POOL_OBSERVED_")):
            return
        until = record.cooldown_until
        affected = []
        for other in self.keys:
            if other is record or other.pool != record.pool:
                continue
            if other.key_validity == "INVALID" or other.cooldown_until >= until:
                continue
            other.cooldown_until = until
            other.cooldown_kind = "daily" if daily else "per_minute"
            if daily:
                other.quota_state = "QUOTA_EXHAUSTED"
            elif other.quota_state == "AVAILABLE":
                other.quota_state = "RATE_LIMITED"
            affected.append(other.label)
        if affected:
            self.events.append({
                "at": _now(), "event": "pool_cooldown", "key": record.label,
                "pool": record.pool, "keys": affected, "cooldown_s": cooldown,
                "kind": "daily" if daily else "per_minute",
            })

    def _observe_independence(self, record: KeyRecord, other_label: str, quota_id: str) -> None:
        other = next((k for k in self.keys if k.label == other_label), None)
        if other is None:
            return
        if other.pool.startswith("POOL_OBSERVED") or other.pool.startswith("POOL_SHARED"):
            record.pool = other.pool
        else:
            self._pool_serial += 1
            label = f"POOL_OBSERVED_{self._pool_serial}"
            record.pool = label
            other.pool = label
        self.events.append({
            "at": _now(), "event": "pool_observed_independent",
            "keys": [other_label, record.label], "pool": record.pool,
            "quota_id": quota_id,
            "evidence": "one key answered immediately after the other was rate-limited",
        })

    def _infer_pools(self) -> None:
        buckets: dict[str, list[KeyRecord]] = {}
        for record in self.keys:
            if record.last_quota_id:
                buckets.setdefault(record.last_quota_id, []).append(record)
        for quota_id, members in buckets.items():
            if len(members) < 2:
                continue
            self._pool_serial += 1
            label = f"POOL_SHARED_{self._pool_serial}"
            for record in members:
                record.pool = label
            self.events.append({"at": _now(), "event": "pool_shared_quota_id",
                                "keys": [m.label for m in members], "pool": label,
                                "quota_id": quota_id})
            now = time.time()
            for member in members:
                if member.cooldown_until > now:
                    self._apply_pool_cooldown(
                        member, member.cooldown_until - now,
                        member.cooldown_kind == "daily")

    def coverage(self) -> dict:
        eligible = [k for k in self.keys
                    if k.key_validity == "VALID"
                    and k.network_state != "UNREACHABLE"
                    and (k.probe_state == "healthy" or k.successes > 0)]
        used = [k for k in eligible if k.benchmark_successes > 0]
        unused = []
        for key in self.keys:
            if key.benchmark_successes > 0:
                continue
            if key.key_validity == "INVALID":
                reason = f"invalid key ({key.last_error_code or 'auth error'})"
            elif key.network_state == "UNREACHABLE":
                reason = f"unreachable ({key.last_error_code or 'network error'})"
            elif key.quota_state == "QUOTA_EXHAUSTED":
                reason = "quota exhausted during the experiment"
            elif key.quota_state == "RATE_LIMITED":
                reason = "rate-limited for the whole window"
            elif key.probe_state != "healthy":
                reason = f"probe state {key.probe_state}"
            else:
                reason = "not selected before the workload ended"
            unused.append({"label": key.label, "reason": reason})
        return {
            "keys_total": len(self.keys),
            "eligible_keys": len(eligible),
            "keys_used_in_benchmark": len(used),
            "successful_benchmark_requests": sum(key.benchmark_successes for key in used),
            "unused_keys": unused,
            "min_successful_requests_for_full_coverage": len(eligible),
            "full_coverage_achieved": len(eligible) == len(used),
            "keys": [key.as_dict() for key in self.keys],
            "pools": self.pool_summary(),
            "events": list(self.events),
        }

    def pool_summary(self) -> dict:
        summary: dict[str, dict] = {}
        for record in self.keys:
            entry = summary.setdefault(record.pool, {
                "keys": [], "requests": 0, "successes": 0,
                "benchmark_successes": 0, "rate_limit_hits": 0,
            })
            entry["keys"].append(record.label)
            entry["requests"] += record.requests
            entry["successes"] += record.successes
            entry["benchmark_successes"] += record.benchmark_successes
            entry["rate_limit_hits"] += record.rate_limit_hits
        return summary

    def _save(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "updated_at": _now(),
                "keys": [record.as_dict() for record in self.keys],
                "events": self.events,
            }
            self.state_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass


def _quota_state(response: dict) -> str:
    return "QUOTA_EXHAUSTED" if response.get("daily_quota") else "RATE_LIMITED"


def _no_key_reason(keys: list[KeyRecord]) -> str:
    states = ", ".join(f"{k.label}={k.key_validity}/{k.quota_state}/{k.network_state}"
                       for k in keys)
    return f"no eligible key: {states}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_time(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
