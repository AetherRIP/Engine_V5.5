"""Run the final A/B/C comparison for a paper outside the historical dataset.

The marking implementations are the existing ones: ``strategies.StrategyRunner``,
``execution.Executor``, ``provider.GeminiClient``, ``keypool.KeyPool``,
``schema``, ``verifier``, ``evaluator`` and ``usage`` are imported unchanged.
Only the paper scope (paths, paper id, reference, ledger) and the orchestration
are new, so no historical ``paper-01`` result is read or overwritten.

Usage:
    python -m benchmark.code.run_final_test --estimate-only
    python -m benchmark.code.run_final_test --runs 2
    python -m benchmark.code.run_final_test --runs 2 --resume
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config, evaluator, final_metrics, ground_truth, loader, report, usage
from .execution import Executor, ModelSelection, select_models
from .keypool import KeyPool
from .provider import GeminiClient
from .run_benchmark import _probe_rows
from .strategies import StrategyRunner

PAPER_ID = "ch2-l3-final-01"
FINAL_DIR = config.BENCHMARK_DIR / "final_tests" / PAPER_ID
ORDER = [("a", 1), ("b", 1), ("c", 1), ("a", 2), ("b", 2), ("c", 2)]

# Historical measured per-run token averages for a workbook of this size, used
# only for the pre-flight estimate. They are labelled as estimates in the output.
ESTIMATE_TOKENS = {
    "a": (31800, 5700, 1),
    "b": (41800, 19200, 14),
    "c": (41000, 19500, 8),
}
COMPLETE_STATES = {"complete", "complete_after_split", "incomplete_output", "incomplete_request"}


def configure() -> None:
    """Point every module at the final-test paper, never at paper-01."""
    config.PAPER_ID = PAPER_ID
    config.SAMPLES_DIR = FINAL_DIR / "inputs"
    config.GROUND_TRUTH_DIR = FINAL_DIR / "reference"
    config.RESULTS_DIR = FINAL_DIR / "results"
    config.REPORTS_DIR = FINAL_DIR / "reports"
    config.USAGE_LOG_PATH = config.RESULTS_DIR / "API_USAGE.jsonl"
    config.KEY_STATE_PATH = config.RESULTS_DIR / "key_pool_state.json"
    config.MANIFEST_PATH = FINAL_DIR / "manifest.json"


def _payload_mb() -> float:
    total = 0
    for page in loader.student_pages() + loader.scheme_pages():
        total += len(page.part()["inline_data"]["data"])
    return round(total / (1024 * 1024), 2)


def _estimate(runs: int) -> dict:
    pricing = config.load_pricing()
    primary = pricing.get(config.PRIMARY_MODEL)
    lite = pricing.get(config.LITE_MODEL) or pricing.get("gemini-3.5-flash-lite")
    total_low = total_high = 0.0
    per_strategy = {}
    for strategy, (input_tokens, output_tokens, requests) in ESTIMATE_TOKENS.items():
        if strategy == "c" and lite is not None:
            primary_share = 2 / requests
            cost = (input_tokens * primary_share * primary.input_per_million
                    + output_tokens * primary_share * primary.output_per_million
                    + input_tokens * (1 - primary_share) * lite.input_per_million
                    + output_tokens * (1 - primary_share) * lite.output_per_million) / 1_000_000
        elif primary is not None:
            cost = (input_tokens * primary.input_per_million
                    + output_tokens * primary.output_per_million) / 1_000_000
        else:
            cost = 0.0
        low, high = cost * runs, cost * runs * 1.6
        total_low += low
        total_high += high
        per_strategy[strategy] = {
            "requests_per_run": requests,
            "estimate_usd_per_run": round(cost, 6),
            "estimate_usd_for_runs": [round(low, 6), round(high, 6)],
        }
    escalations = config.MAX_ESCALATIONS_PER_RUN * runs
    return {
        "basis": "historical measured token averages for a same-size workbook; not a quote",
        "runs_per_strategy": runs,
        "planned_benchmark_requests": sum(v[2] for v in ESTIMATE_TOKENS.values()) * runs,
        "max_escalation_requests": escalations,
        "per_strategy": per_strategy,
        "estimate_usd_range": [round(total_low, 4), round(total_high + 0.02 * escalations, 4)],
        "probe_requests": "20 key probes + up to 9 model-verification probes; excluded from benchmark totals but consumed",
        "a_whole_paper_payload_mb": _payload_mb(),
    }


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Final A/B/C comparison, ch2-l3-final-01")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--resume", action="store_true",
                        help="skip attempts whose raw file already records a completed run")
    parser.add_argument("--max-requests", type=int, default=config.MAX_BENCHMARK_REQUESTS)
    parser.add_argument("--order", default="",
                        help="comma-separated strategy:run pairs, default A1,B1,C1,A2,B2,C2")
    parser.add_argument("--skip-probe", action="store_true",
                        help="restore key state instead of re-probing every key")
    parser.add_argument("--models", default="",
                        help="fixed primary,lite,strong model ids; skips model-verification probes")
    args = parser.parse_args(argv)

    configure()
    config.ensure_dirs()

    reference = ground_truth.load()
    problems = ground_truth.validate(reference)
    if problems:
        print("REFERENCE INVALID: " + "; ".join(problems), file=sys.stderr)
        return 2
    if reference.get("paper_id") != PAPER_ID:
        print(f"reference paper_id {reference.get('paper_id')!r} is not {PAPER_ID!r}", file=sys.stderr)
        return 2
    if reference["totals"]["marks_available_scored"] != 87 or \
            reference["totals"]["candidate_marks_awarded"] != 76:
        print("reference does not reconcile to 76/87 (11 lost)", file=sys.stderr)
        return 2

    estimate = _estimate(args.runs)
    print("PRE-FLIGHT ESTIMATE")
    print(json.dumps(estimate, indent=2))
    if args.estimate_only:
        _write(config.RESULTS_DIR / "cost_estimate.json", estimate)
        return 0

    keys = config.read_api_keys()
    if not keys:
        print("no API keys configured; cannot run the live comparison", file=sys.stderr)
        return 3
    client = GeminiClient()
    ledger = usage.UsageLedger()
    if args.skip_probe:
        pool = KeyPool.from_state(keys)
        print("Probe skipped; key state restored from key_pool_state.json")
    else:
        pool = KeyPool(keys)
        print(f"Probing {len(pool.keys)} keys (values are never printed)...")
        probes = pool.probe(client)
        for row in _probe_rows(pool, probes):
            ledger.record(**row)
        for state in pool.coverage()["keys"]:
            print(f"  {state['label']}: {state['key_validity']} / {state['quota_state']} / "
                  f"{state['network_state']} / {state['pool']}")
        _write(config.RESULTS_DIR / "key_coverage_after_probe.json", pool.coverage())
    if args.probe_only:
        return 0

    if args.models:
        primary, lite, strong = [part.strip() for part in args.models.split(",")]
        models = ModelSelection(primary=primary, lite=lite or None,
                                strong=strong or primary,
                                notes=["fixed by --models without re-probing"])
    else:
        models = select_models(client, pool, ledger)
    print("Models: " + json.dumps(models.as_dict()))
    executor = Executor(client, pool, ledger)
    runner = StrategyRunner(executor, models)

    if args.order:
        order = []
        for token in args.order.split(","):
            strategy, run = token.split(":")
            order.append((strategy.strip().lower(), int(run)))
    else:
        order = [pair for pair in ORDER if pair[1] <= args.runs]

    raw_dir = config.RESULTS_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for strategy, run in order:
        target = raw_dir / f"{strategy}_run{run}.json"
        if args.resume and target.is_file():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if existing.get("completion_status") in COMPLETE_STATES:
                print(f"Skipping {strategy.upper()}{run}: {existing.get('completion_status')} already recorded")
                continue
        used = len([row for row in ledger.rows() if row.get("purpose") != "probe"])
        if used >= args.max_requests:
            print(f"request cap reached ({used}); stopping before {strategy.upper()}{run}")
            break
        print(f"Running strategy {strategy.upper()} run {run}...")
        if strategy == "a":
            outcome = runner.run_a(run)
        elif strategy == "b":
            outcome = runner.run_b(run)
        else:
            outcome = runner.run_c(run)
        payload = outcome.as_dict()
        payload["paper_id"] = PAPER_ID
        _write(target, payload)
        print(f"  requests={outcome.request_count} items={len(outcome.final_items)} "
              f"invalid={outcome.invalid_responses} status={outcome.completion_status} "
              f"errors={len(outcome.errors)}")

    # Evaluate every attempt recorded for this paper, not just this invocation.
    strategy_runs: dict[str, list[dict]] = {}
    for path in sorted(raw_dir.glob("*_run*.json")):
        strategy = path.name.split("_", 1)[0]
        payload = json.loads(path.read_text(encoding="utf-8"))
        strategy_runs.setdefault(strategy, []).append(payload)
    for strategy in strategy_runs:
        strategy_runs[strategy].sort(key=lambda item: item.get("run", 0))

    accuracy_runs = {strategy: [evaluator.evaluate_run(run, reference) for run in runs]
                     for strategy, runs in strategy_runs.items()}
    evaluator.write_accuracy(accuracy_runs)

    rows = ledger.rows()
    benchmark_rows = [row for row in rows if row.get("purpose") != "probe"]
    for strategy, runs in strategy_runs.items():
        strategy_rows = report.selected_strategy_rows(strategy, benchmark_rows, runs)
        report.write_strategy_result(strategy, runs, accuracy_runs[strategy],
                                     usage.aggregate(strategy_rows))

    comparison = report.build_comparison(strategy_runs, rows, pool.coverage())
    comparison["paper_id"] = PAPER_ID
    comparison["reference_status"] = reference["verification"]["status"]
    comparison["paper_max_marks"] = reference["totals"]["marks_available_scored"]
    comparison["paper_reference_marks"] = reference["totals"]["candidate_marks_awarded"]
    comparison["reference_marks_lost"] = reference["totals"]["marks_lost_eligible"]
    comparison["reference_band"] = reference.get("reference_range")
    comparison["definitions"]["within_band"] = (
        "paper total inside the human tolerance band around the 76-mark centre; "
        "exact equality to 76 is reported separately")
    comparison["estimate"] = estimate
    for strategy, runs in strategy_runs.items():
        band_runs = [final_metrics.band_evaluate(run, reference) for run in runs]
        comparison["strategies"][strategy]["band_accuracy_per_run"] = band_runs
        comparison["strategies"][strategy]["band_summary"] = final_metrics.summarise_band(band_runs)
        cost = comparison["strategies"][strategy]["usage"].get("cost_usd")
        within = sum(1 for row in band_runs if row["within_band"])
        comparison["strategies"][strategy]["cost_per_within_band_paper_usd"] = (
            round(cost / within, 8) if cost is not None and within else None)
    _write(config.RESULTS_DIR / "STRATEGY_COMPARISON.json", comparison)
    _write(config.RESULTS_DIR / "comparison.json", comparison)

    audit = report.coverage_audit(rows, pool.coverage())
    report.write_coverage(audit)
    _write(config.RESULTS_DIR / "key_coverage.json", audit)

    print(json.dumps({
        "paper_id": PAPER_ID,
        "attempts": {strategy: [run.get("run") for run in runs]
                     for strategy, runs in strategy_runs.items()},
        "benchmark_requests": len(benchmark_rows),
        "probe_requests": len(rows) - len(benchmark_rows),
        "keys": {"eligible": audit["eligible_keys"],
                 "used": audit["keys_with_successful_benchmark_request"],
                 "full_coverage": audit["full_coverage_achieved"]},
        "accuracy": {strategy: evaluator.summarise(accuracy_runs[strategy])
                     for strategy in accuracy_runs},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
