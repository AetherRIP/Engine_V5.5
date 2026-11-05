"""Evaluate the preserved final-test attempts without calling the provider.

The live runner evaluates at the end of a run, but the provider 503 storm and
the 80-request cap stopped it before that block.  This module reuses the same
``evaluator``, ``report`` and ``final_metrics`` functions on the raw files that
were already written.  It makes no API request and does not rewrite any raw
response or ledger row.

    python -m benchmark.code.evaluate_final_test
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config, evaluator, final_metrics, ground_truth, report, usage
from .keypool import KeyPool
from .run_final_test import PAPER_ID, configure


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def main() -> int:
    configure()
    config.ensure_dirs()
    reference = ground_truth.load()
    problems = ground_truth.validate(reference)
    if problems:
        raise SystemExit("reference invalid: " + "; ".join(problems))
    if reference.get("paper_id") != PAPER_ID:
        raise SystemExit(f"reference paper_id is not {PAPER_ID}")

    raw_dir = config.RESULTS_DIR / "raw"
    strategy_runs: dict[str, list[dict]] = {}
    for path in sorted(raw_dir.glob("*_run*.json")):
        strategy = path.name.split("_", 1)[0]
        strategy_runs.setdefault(strategy, []).append(
            json.loads(path.read_text(encoding="utf-8")))
    for strategy in strategy_runs:
        strategy_runs[strategy].sort(key=lambda item: item.get("run", 0))

    accuracy_runs = {strategy: [evaluator.evaluate_run(run, reference) for run in runs]
                     for strategy, runs in strategy_runs.items()}
    evaluator.write_accuracy(accuracy_runs)

    ledger = usage.UsageLedger()
    rows = ledger.rows()
    benchmark_rows = [row for row in rows if row.get("purpose") != "probe"]
    for strategy, runs in strategy_runs.items():
        strategy_rows = report.selected_strategy_rows(strategy, benchmark_rows, runs)
        report.write_strategy_result(strategy, runs, accuracy_runs[strategy],
                                     usage.aggregate(strategy_rows))

    keys = config.read_api_keys()
    if not keys:
        raise SystemExit("no API keys configured; cannot load the key state for coverage")
    pool = KeyPool.from_state(keys)
    coverage = pool.coverage()

    comparison = report.build_comparison(strategy_runs, rows, coverage)
    comparison["paper_id"] = PAPER_ID
    comparison["reference_status"] = reference["verification"]["status"]
    comparison["paper_max_marks"] = reference["totals"]["marks_available_scored"]
    comparison["paper_reference_marks"] = reference["totals"]["candidate_marks_awarded"]
    comparison["reference_marks_lost"] = reference["totals"]["marks_lost_eligible"]
    comparison["reference_band"] = reference.get("reference_range")
    comparison["definitions"]["within_band"] = (
        "paper total inside the human tolerance band around the 76-mark centre; "
        "exact equality to 76 is reported separately")
    estimate_path = config.RESULTS_DIR / "cost_estimate.json"
    comparison["estimate"] = (json.loads(estimate_path.read_text(encoding="utf-8"))
                              if estimate_path.is_file() else None)
    for strategy, runs in strategy_runs.items():
        band_runs = [final_metrics.band_evaluate(run, reference) for run in runs]
        entry = comparison["strategies"][strategy]
        entry["band_accuracy_per_run"] = band_runs
        entry["band_summary"] = final_metrics.summarise_band(band_runs)
        cost = entry["usage"].get("cost_usd")
        within = sum(1 for row in band_runs if row["within_band"])
        entry["cost_per_within_band_paper_usd"] = (
            round(cost / within, 8) if cost is not None and within else None)
    _write(config.RESULTS_DIR / "STRATEGY_COMPARISON.json", comparison)
    _write(config.RESULTS_DIR / "comparison.json", comparison)

    audit = report.coverage_audit(rows, coverage)
    report.write_coverage(audit)
    _write(config.RESULTS_DIR / "key_coverage.json", audit)

    print(json.dumps({
        "paper_id": PAPER_ID,
        "attempts": {strategy: [run.get("run") for run in runs]
                     for strategy, runs in strategy_runs.items()},
        "benchmark_requests": len(benchmark_rows),
        "probe_requests": len(rows) - len(benchmark_rows),
        "band": {strategy: comparison["strategies"][strategy]["band_summary"]
                 for strategy in strategy_runs},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
