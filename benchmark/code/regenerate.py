"""Regenerate results and reports from the preserved raw runs and ledger.

This exists because reports are derived artifacts: a formatting or measurement
fix must not require spending API quota again.  It never contacts a provider.

    python -m benchmark.code.regenerate
"""

from __future__ import annotations

import json

from . import config, evaluator, ground_truth, report, usage


def load_strategy_runs(strategy: str, results_dir=None) -> list[dict]:
    """Load the current pair while retaining historical raw files on disk.

    Strategy C can be rerun append-only. Only a rerun whose two runs were marked
    valid is promoted; otherwise the historical C1/C2 pair remains the displayed
    (documented-deviation) result.
    """
    results_dir = results_dir or config.RESULTS_DIR
    raw_dir = results_dir / "raw"
    payloads = []
    for path in sorted(raw_dir.glob(f"{strategy}_run*.json")) if raw_dir.is_dir() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        payloads.append(payload)
    if strategy == "c":
        valid = [p for p in payloads if p.get("attempt_status") == "valid"]
        if valid:
            return sorted(valid, key=lambda p: p.get("run", 0))[-2:]
        historical = [p for p in payloads if p.get("run") in (1, 2)]
        return sorted(historical, key=lambda p: p.get("run", 0))[-2:]
    return payloads[-2:]


def _pool_state(keys_state: dict) -> dict:
    keys = keys_state.get("keys", [])
    eligible = [key for key in keys
                if key.get("key_validity") == "VALID"
                and key.get("network_state") != "UNREACHABLE"
                and (key.get("probe_state") == "healthy" or key.get("successes", 0) > 0)]
    pools: dict[str, dict] = {}
    for key in keys:
        entry = pools.setdefault(key["pool"], {"keys": [], "requests": 0, "successes": 0,
                                               "benchmark_successes": 0, "rate_limit_hits": 0})
        entry["keys"].append(key["label"])
        for name in ("requests", "successes", "benchmark_successes", "rate_limit_hits"):
            entry[name] += key.get(name, 0)
    unused = []
    for key in keys:
        if key.get("benchmark_successes", 0) > 0:
            continue
        if key.get("key_validity") == "INVALID":
            reason = f"invalid key ({key.get('last_error_code') or 'auth error'})"
        elif key.get("network_state") == "UNREACHABLE":
            reason = "unreachable"
        elif key.get("quota_state") == "QUOTA_EXHAUSTED":
            reason = "quota exhausted during the experiment"
        elif key.get("probe_state") not in {"healthy"}:
            reason = f"probe state {key.get('probe_state')}"
        else:
            reason = "not selected before the workload ended"
        unused.append({"label": key["label"], "reason": reason})
    used = [key for key in eligible if key.get("benchmark_successes", 0) > 0]
    return {
        "keys_total": len(keys),
        "eligible_keys": len(eligible),
        "keys_used_in_benchmark": len(used),
        "successful_benchmark_requests": sum(key.get("benchmark_successes", 0) for key in used),
        "min_successful_requests_for_full_coverage": len(eligible),
        "full_coverage_achieved": len(used) == len(eligible),
        "keys": keys,
        "pools": pools,
        "unused_keys": unused,
    }


def main() -> int:
    reference = ground_truth.load()
    manifest = json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))
    keys_state = json.loads(config.KEY_STATE_PATH.read_text(encoding="utf-8"))
    rows = usage.UsageLedger().rows()

    strategy_runs: dict[str, list[dict]] = {}
    for strategy in ("a", "b", "c"):
        runs = load_strategy_runs(strategy)
        if runs:
            strategy_runs[strategy] = runs

    accuracy_runs = {strategy: [evaluator.evaluate_run(run, reference) for run in runs]
                     for strategy, runs in strategy_runs.items()}
    evaluator.write_accuracy(accuracy_runs)

    benchmark_rows = [row for row in rows if row.get("purpose") != "probe"]
    for strategy, runs in strategy_runs.items():
        strategy_rows = report.selected_strategy_rows(strategy, benchmark_rows, runs)
        report.write_strategy_result(strategy, runs, accuracy_runs[strategy],
                                     usage.aggregate(strategy_rows))

    state = _pool_state(keys_state)
    comparison = report.build_comparison(strategy_runs, rows, state)
    if "c" in comparison["strategies"]:
        attempts = []
        for path in sorted((config.RESULTS_DIR / "raw").glob("c_run*.json")):
            try:
                attempt = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            attempts.append({
                "run": attempt.get("run"),
                "attempt_id": attempt.get("attempt_id"),
                "attempt_status": attempt.get("attempt_status"),
                "attempt_status_reason": attempt.get("attempt_status_reason"),
                "different_checks": sum(
                    1 for check in (attempt.get("verification") or {}).values()
                    if isinstance(check, dict) and check.get("status") == "different"),
                "escalation_count": len(attempt.get("escalations") or []),
            })
        comparison["strategies"]["c"]["attempts"] = attempts
        replay_path = config.RESULTS_DIR / "c_escalation_replay.json"
        if replay_path.is_file():
            comparison["strategies"]["c"]["replay_evidence"] = json.loads(
                replay_path.read_text(encoding="utf-8"))
        live_path = config.RESULTS_DIR / "live_escalation.json"
        if live_path.is_file():
            live = json.loads(live_path.read_text(encoding="utf-8"))
            if live.get("valid_changed_mark"):
                comparison["strategies"]["c"]["live_escalation"] = live
    report.write_comparison(comparison)
    audit = report.coverage_audit(rows, state)
    report.write_coverage(audit)
    report.write_reports(comparison, audit, reference, manifest)

    print(json.dumps({
        "strategies": {key: {"runs": len(runs),
                             "means": evaluator.summarise(accuracy_runs[key]),
                             "correct": sum(1 for r in accuracy_runs[key] if r["strict_correct"]),
                             "near": sum(1 for r in accuracy_runs[key] if r["near_correct_within_one"]),
                             "cost_usd": comparison["strategies"][key]["usage"].get("cost_usd"),
                             "requests": comparison["strategies"][key]["usage"].get("requests")}
                       for key in strategy_runs},
        "keys": {"total": audit["keys_total"], "eligible": audit["eligible_keys"],
                 "used": audit["keys_with_successful_benchmark_request"],
                 "full": audit["full_coverage_achieved"],
                 "inconsistencies": audit["inconsistencies"]},
        "probe_rows": audit["probe_rows"],
        "benchmark_rows": audit["benchmark_rows"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
