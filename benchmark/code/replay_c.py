"""Replay Strategy C differences through the repaired escalation guard.

This is an offline diagnostic only.  It makes no provider calls and does not
alter any raw run.  It has two evidence sources:

* the historical C1/C2 verification records whose raw status is ``different``;
* the preserved C5/C6 verifier inputs whose raw status is ``unknown`` but whose
  student/expected pair the current classifier re-evaluates as ``different``.

Both sets are replayed through the current ``_escalation_reason``.  The pre-fix
guard is reproduced by its old requirements: it read the raw status, required a
check-level ``expected`` field, and could not use a re-evaluated status.  The
resulting JSON is evidence about the guard, not a new benchmark run and not a
live measurement.  Reports must label it as replay evidence.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import config, verifier
from .strategies import _escalation_reason

HISTORICAL_RUNS = (1, 2)
CURRENT_RUNS = (5, 6)


def _pre_fix_reason(item: dict, raw_check: dict) -> str:
    """Reproduce the historical guard's unreachable ``different`` branch.

    The old guard could only escalate a raw ``different`` check that also
    carried a check-level ``expected`` value.  The historical records did not
    carry that field, and the C5/C6 re-evaluated checks were raw ``unknown``.
    Passing the raw check here is therefore essential: it shows the pre-fix gap
    rather than retroactively escalating the re-evaluated result.
    """
    if raw_check.get("status") == "different" and raw_check.get("expected"):
        return "SymPy says transcribed answer differs from the scheme's expected answer"
    return ""


def _record(item: dict, run_id: int, item_id: str, raw_check: dict,
            re_evaluated_check: dict, source_kind: str) -> dict:
    fixed_reason = _escalation_reason(item, re_evaluated_check)
    pre_fix_reason = _pre_fix_reason(item, raw_check)
    return {
        "source_kind": source_kind,
        "source_run": run_id,
        "item": str(item_id),
        "raw_status": raw_check.get("status"),
        "re_evaluated_status": re_evaluated_check.get("status"),
        "difference": re_evaluated_check.get("detail", raw_check.get("detail", "")),
        "pre_fix_escalated": bool(pre_fix_reason),
        "fixed_escalated": bool(fixed_reason),
        "fixed_reason": fixed_reason,
    }


def build_replay(results_dir: Path | None = None) -> dict:
    results_dir = results_dir or config.RESULTS_DIR
    records: list[dict] = []
    historical_count = 0
    current_raw_different = 0
    recovered_by_run: dict[str, int] = {}

    for run_id in HISTORICAL_RUNS:
        path = results_dir / "raw" / f"c_run{run_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = {str(item.get("id")): item for item in payload.get("items", [])}
        for item_id, raw_check in (payload.get("verification") or {}).items():
            if not isinstance(raw_check, dict) or raw_check.get("status") != "different":
                continue
            historical_count += 1
            records.append(_record(items.get(str(item_id)) or {}, run_id, item_id,
                                   raw_check, raw_check, "historical_raw_different"))

    for run_id in CURRENT_RUNS:
        path = results_dir / "raw" / f"c_run{run_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = {str(item.get("id")): item for item in payload.get("items", [])}
        checks = payload.get("verification") or {}
        run_recovered = 0
        for item_id, raw_check in checks.items():
            if not isinstance(raw_check, dict):
                continue
            if raw_check.get("status") == "different":
                current_raw_different += 1
                continue
            if not raw_check.get("student") or not raw_check.get("expected"):
                continue
            re_evaluated = verifier.equivalent(raw_check["student"], raw_check["expected"])
            if re_evaluated.get("status") != "different":
                continue
            run_recovered += 1
            records.append(_record(items.get(str(item_id)) or {}, run_id, item_id,
                                   raw_check, re_evaluated, "recovered_from_raw_unknown"))
        recovered_by_run[str(run_id)] = run_recovered

    recovered_total = sum(recovered_by_run.values())
    fixed_count = sum(1 for record in records if record["fixed_escalated"])
    pre_fix_count = sum(1 for record in records if record["pre_fix_escalated"])
    return {
        "kind": "offline_replay",
        "measurement_kind": "replay_not_live",
        "label": (
            "Historical C1/C2 raw differences plus C5/C6 differences recovered by "
            "the fixed classifier, replayed through the repaired escalation guard; "
            "no provider calls, no new benchmark run, and no raw files rewritten."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "live_api_calls": 0,
        "raw_files_modified": False,
        "source_runs": [*HISTORICAL_RUNS, *CURRENT_RUNS],
        "source_artifacts": [f"raw/c_run{run_id}.json"
                             for run_id in (*HISTORICAL_RUNS, *CURRENT_RUNS)],
        "historical_raw": {
            "runs": list(HISTORICAL_RUNS),
            "raw_different": historical_count,
        },
        "current_raw": {
            "runs": list(CURRENT_RUNS),
            "raw_different": current_raw_different,
            "re_evaluated_different": recovered_total,
            "by_run": recovered_by_run,
        },
        "raw_different": historical_count + current_raw_different,
        "different_checks": len(records),
        "pre_fix": {
            "escalations": pre_fix_count,
            "escalation_gap": pre_fix_count < len(records),
        },
        "fixed": {
            "escalations": fixed_count,
            "escalation_gap": fixed_count < len(records),
        },
        "records": records,
    }


def write_replay(results_dir: Path | None = None) -> dict:
    results_dir = results_dir or config.RESULTS_DIR
    payload = build_replay(results_dir)
    (results_dir / "c_escalation_replay.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    payload = write_replay()
    print(json.dumps({
        "kind": payload["kind"],
        "measurement_kind": payload["measurement_kind"],
        "historical_raw": payload["historical_raw"],
        "current_raw": payload["current_raw"],
        "different_checks": payload["different_checks"],
        "pre_fix": payload["pre_fix"],
        "fixed": payload["fixed"],
        "live_api_calls": payload["live_api_calls"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
