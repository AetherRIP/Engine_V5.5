"""Run the live benchmark end to end.

Usage:
    python -m benchmark.code.run_benchmark --probe-only
    python -m benchmark.code.run_benchmark --runs 2
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config, evaluator, ground_truth, loader, report, usage
from .execution import Executor, select_models
from .keypool import KeyPool
from .provider import GeminiClient
from .strategies import StrategyRunner


def _probe_rows(pool: KeyPool, probes: list[dict]) -> list[dict]:
    rows = []
    states = {key.label: key.as_dict() for key in pool.keys}
    for probe in probes:
        state = states.get(probe.get("label"), {})
        generate = probe.get("generate") or {}
        rows.append({
            "strategy": "probe", "run": 0, "batch": "key-discovery",
            "item_ids": [], "model": generate.get("model") or config.PRIMARY_MODEL,
            "purpose": "probe", "key_label": state.get("label", probe.get("label")),
            "finish_reason": generate.get("finish_reason", ""),
            "pool": state.get("pool"), "key_validity": state.get("key_validity"),
            "quota_state": state.get("quota_state"), "network_state": state.get("network_state"),
            "input_tokens": (generate.get("usage") or {}).get("input_tokens"),
            "output_tokens": (generate.get("usage") or {}).get("output_tokens"),
            "cached_tokens": None, "thoughts_tokens": (generate.get("usage") or {}).get("thoughts_tokens"),
            "total_tokens": (generate.get("usage") or {}).get("total_tokens"),
            "image_tokens": None,
            "reported_usage": bool((generate.get("usage") or {}).get("reported")),
            "estimated_usage": False,
            "latency_ms": generate.get("latency_ms"), "http_status": generate.get("http_status"),
            "error_class": "" if generate.get("status") == "ok" else generate.get("status"),
            "error_code": generate.get("error_code", ""), "retry_after_s": None,
            "cooldown_s": None, "attempt": 1, "escalated": False,
            "success": generate.get("status") == "ok",
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MathChecker correction-strategy benchmark")
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--strategies", default="a,b,c")
    parser.add_argument("--max-requests", type=int, default=config.MAX_BENCHMARK_REQUESTS)
    parser.add_argument("--keep-ledger", action="store_true",
                        help="append to the existing api_usage.jsonl instead of starting a fresh file")
    args = parser.parse_args(argv)

    config.ensure_dirs()
    reference = ground_truth.load()
    problems = ground_truth.validate(reference)
    if problems:
        print("GROUND TRUTH INVALID: " + "; ".join(problems), file=sys.stderr)
        return 2
    if not config.MANIFEST_PATH.is_file():
        print("dataset manifest missing; run benchmark.code.anonymize first", file=sys.stderr)
        return 2

    if not args.keep_ledger and config.USAGE_LOG_PATH.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = config.USAGE_LOG_PATH.with_name(f"api_usage.previous-{stamp}.jsonl")
        shutil.move(str(config.USAGE_LOG_PATH), str(backup))

    keys = config.read_api_keys()
    if not keys:
        print("no API keys configured; cannot run live benchmark", file=sys.stderr)
        return 3
    pool = KeyPool(keys)
    client = GeminiClient()
    ledger = usage.UsageLedger()

    print(f"Probing {len(pool.keys)} keys (values never printed)...")
    probes = pool.probe(client)
    for row in _probe_rows(pool, probes):
        ledger.record(**row)
    print("Key probe states:")
    for state in pool.coverage()["keys"]:
        print(f"  {state['label']}: {state['key_validity']} / {state['quota_state']} / "
              f"{state['network_state']} / {state['pool']}")
    if args.probe_only:
        return 0

    eligible = pool.coverage()["eligible_keys"]
    planned_min = sum(config.STRATEGY_BATCHES.values()) * args.runs
    planned_max = planned_min + config.MAX_ESCALATIONS_PER_RUN * args.runs
    print(f"Eligible keys: {eligible}; planned benchmark requests: {planned_min}–{planned_max}")
    print(f"Coverage requires at least {eligible} successful benchmark requests.")

    models = select_models(client, pool, ledger)
    print("Models: " + json.dumps(models.as_dict()))
    executor = Executor(client, pool, ledger)
    runner = StrategyRunner(executor, models)

    strategy_runs: dict[str, list[dict]] = {}
    run_order = [(strategy, run) for run in range(1, args.runs + 1)
                 for strategy in ("a", "b", "c")
                 if strategy in args.strategies.split(",")]
    for strategy, run in run_order:
        used = len([row for row in ledger.rows() if row.get("purpose") != "probe"])
        if used >= args.max_requests:
            print(f"request cap reached ({used}); stopping before {strategy}{run}")
            break
        print(f"Running strategy {strategy.upper()} run {run}...")
        if strategy == "a":
            outcome = runner.run_a(run)
        elif strategy == "b":
            outcome = runner.run_b(run)
        else:
            outcome = runner.run_c(run)
        payload = outcome.as_dict()
        strategy_runs.setdefault(strategy, []).append(payload)
        raw_dir = config.RESULTS_DIR / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"{strategy}_run{run}.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"  requests={outcome.request_count} items={len(outcome.final_items)} "
              f"invalid={outcome.invalid_responses} errors={len(outcome.errors)}")

    rows = ledger.rows()
    state = pool.coverage()
    accuracy_runs: dict[str, list[dict]] = {}
    for strategy, runs in strategy_runs.items():
        accuracy_runs[strategy] = [evaluator.evaluate_run(run) for run in runs]
    evaluator.write_accuracy(accuracy_runs)

    benchmark_rows = [row for row in rows if row.get("purpose") != "probe"]
    for strategy, runs in strategy_runs.items():
        strategy_rows = report.selected_strategy_rows(strategy, benchmark_rows, runs)
        report.write_strategy_result(strategy, runs, accuracy_runs[strategy],
                                     usage.aggregate(strategy_rows))

    comparison = report.build_comparison(strategy_runs, rows, state)
    report.write_comparison(comparison)
    audit = report.coverage_audit(rows, state)
    report.write_coverage(audit)
    manifest = json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))
    report.write_reports(comparison, audit, reference, manifest)

    print(json.dumps({
        "runs": {strategy: len(runs) for strategy, runs in strategy_runs.items()},
        "requests": len(benchmark_rows),
        "probe_requests": len(rows) - len(benchmark_rows),
        "keys_used": audit["keys_with_successful_benchmark_request"],
        "full_key_coverage": audit["full_coverage_achieved"],
        "correct": {strategy: sum(1 for run in runs if run["strict_correct"])
                    for strategy, runs in accuracy_runs.items()},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
