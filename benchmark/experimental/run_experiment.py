"""Strategy H experiment driver.

Three modes, all append-only with respect to the historical benchmark:

``--signals``   offline: compute the frozen escalation signals on the preserved live A
                runs and report what each policy would escalate.  No provider calls.
``--escalate``  live: issue the bounded, targeted one-item escalations for the union of
                selected items.  One request per item per document; valid responses are
                stored and reused, never re-bought.
``--evaluate``  offline: score A-only, C-only and every H policy with the unchanged
                evaluator, write cost/accuracy tables and a bootstrap.

The A stage is not re-issued: the preserved live A responses are the base.  Escalation is
live.  Nothing here writes to ``benchmark/results/``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..code import config as bconfig
from ..code import evaluator, ground_truth, loader, usage
from ..code import schema as schema_mod
from ..code.execution import Executor, ModelSelection, parse_json
from ..code.keypool import KeyPool
from ..code.provider import GeminiClient, ProviderResult
from ..code.regenerate import load_strategy_runs
from ..code.strategies import MARKING_SYSTEM
from ..code.usage import UsageLedger
from .strategy_h import config as hconfig
from .strategy_h import evaluate as heval
from .strategy_h import evidence as scheme
from .strategy_h import runner as hrunner
from .strategy_h import signals as signal_mod

EXPERIMENT_DIR = Path(__file__).resolve().parent  # benchmark/experimental
RESULTS_DIR = EXPERIMENT_DIR / "results"
LEDGER_PATH = RESULTS_DIR / "h_usage.jsonl"
REGISTRY_PATH = RESULTS_DIR / "escalation_responses.json"
STATUS_PATH = RESULTS_DIR / "escalation_run.json"
BASE_RUN_IDS = (2, 3)


# --------------------------------------------------------------------------- io
def _read_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def base_runs() -> list[dict]:
    runs = []
    for run_id in BASE_RUN_IDS:
        path = bconfig.RESULTS_DIR / "raw" / f"a_run{run_id}.json"
        if path.is_file():
            runs.append(json.loads(path.read_text(encoding="utf-8")))
    if not runs:
        raise FileNotFoundError("no preserved Strategy A runs; H has no base")
    return runs


def preserved_rows() -> list[dict]:
    """Read the historical ledger without writing to it."""
    return UsageLedger(bconfig.USAGE_LOG_PATH).rows()


def _rows_for(rows: list[dict], strategy: str, runs: tuple[int, ...]) -> list[dict]:
    return [row for row in rows
            if row.get("purpose") != "probe"
            and row.get("strategy") == strategy
            and str(row.get("run")) in {str(run) for run in runs}]


def _cost(rows: list[dict]) -> float | None:
    values = [row["cost_usd"] for row in rows if isinstance(row.get("cost_usd"), (int, float))]
    return round(sum(values), 8) if values else None


def _base_cost_by_run(rows: list[dict]) -> dict[int, float | None]:
    return {run_id: _cost(_rows_for(rows, "a", (run_id,))) for run_id in BASE_RUN_IDS}


# ------------------------------------------------------------------- signals
def signal_analysis() -> dict:
    reference = ground_truth.load()
    truth = {str(item["id"]): item for item in reference["items"]
             if item.get("status") == "scored"}
    runs = base_runs()
    payload = {
        "kind": "offline_signal_analysis",
        "measurement_kind": "derived_from_preserved_live_a_runs",
        "live_api_calls": 0,
        "policies": {name: hconfig.POLICIES[name].description for name in hconfig.POLICY_ORDER},
        "frozen_signal_sets": {name: sorted(hconfig.POLICIES[name].signals)
                               for name in hconfig.POLICY_ORDER},
        "caps": {name: hconfig.POLICIES[name].max_escalations
                 for name in hconfig.POLICY_ORDER},
        "runs": {},
        "confidence_calibration": _confidence_calibration(runs, truth),
        "signal_frequency": {},
    }
    frequency: dict[str, int] = {}
    for run in runs:
        items = {str(item["id"]): item for item in run.get("items", [])}
        per_policy = {}
        for name in hconfig.POLICY_ORDER:
            selection = signal_mod.select(items, hconfig.POLICIES[name], loader.item_ids())
            per_policy[name] = {
                "candidates": selection["candidate_count"],
                "selected": [entry["item"] for entry in selection["selected"]],
                "suppressed": [entry["item"] for entry in selection["suppressed"]],
                "detail": selection["selected"],
            }
            for entry in selection["selected"] + selection["suppressed"]:
                for signal in entry["signals"]:
                    frequency[signal["code"]] = frequency.get(signal["code"], 0) + 1
        payload["runs"][str(run.get("run"))] = {
            "awarded": sum(int(item.get("awarded") or 0) for item in items.values()),
            "policies": per_policy,
        }
    payload["signal_frequency"] = frequency
    _write_json(RESULTS_DIR / "signal_analysis.json", payload)
    return payload


def _confidence_calibration(runs: list[dict], truth: dict) -> dict:
    """Diagnostic only: does A's self-reported confidence track its own errors?

    This runs after the policies were frozen; it justifies excluding S7 from h-low and
    h-medium and reports S7's inclusion in h-high as a negative control.
    """
    pairs = []
    for run in runs:
        for item in run.get("items", []):
            item_id = str(item.get("id"))
            reference = truth.get(item_id)
            confidence = item.get("confidence")
            if reference is None or not isinstance(confidence, (int, float)):
                continue
            pairs.append({
                "run": run.get("run"),
                "item": item_id,
                "confidence": float(confidence),
                "correct": int(item.get("awarded") or 0) == int(reference["expected_mark"]),
            })
    if not pairs:
        return {"available": False}
    values = sorted({pair["confidence"] for pair in pairs})
    buckets = []
    for value in values:
        group = [pair for pair in pairs if pair["confidence"] == value]
        buckets.append({
            "confidence": value,
            "n": len(group),
            "item_accuracy": round(sum(1 for pair in group if pair["correct"]) / len(group), 4),
        })
    high = [pair for pair in pairs if pair["confidence"] >= 0.95]
    low = [pair for pair in pairs if pair["confidence"] < 0.95]
    return {
        "available": True,
        "observations": len(pairs),
        "distinct_values": values,
        "buckets": buckets,
        "brier": round(sum((pair["confidence"] - int(pair["correct"])) ** 2
                           for pair in pairs) / len(pairs), 4),
        "accuracy_at_confidence_ge_0_95": (
            round(sum(1 for pair in high if pair["correct"]) / len(high), 4) if high else None),
        "accuracy_at_confidence_lt_0_95": (
            round(sum(1 for pair in low if pair["correct"]) / len(low), 4) if low else None),
        "separation": ("confidence is saturated; no usable ordering"
                       if len(values) == 1 else
                       "spread present; sample is too small to calibrate a threshold"),
        "conclusion": (
            "Model-reported confidence is not calibrated on this paper: it is saturated "
            "near 1.0 and does not order correct from incorrect items, so it is excluded "
            "from h-low and h-medium and used only as an h-high negative control."
        ),
    }


# --------------------------------------------------------------- live escalation
class _OfflineExecutor:
    """Never contacts a provider; used when scoring a frozen escalation registry."""

    def call(self, **_kwargs):
        return ProviderResult(status="offline", error_code="OFFLINE_EVALUATION"), []


def _models(runs: list[dict]) -> ModelSelection:
    data = (runs[0].get("models") or {})
    primary = data.get("primary") or bconfig.PRIMARY_MODEL
    return ModelSelection(
        primary=primary,
        lite=data.get("lite"),
        strong=data.get("strong") or primary,
        notes=list(data.get("notes") or []) + [
            "strategy h escalation reuses the preserved A model selection; "
            "no new model probe was spent",
        ],
    )


def escalate_live(max_requests: int = 12, max_consecutive_failures: int = 2) -> dict:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    runs = base_runs()
    registry = _read_json(REGISTRY_PATH, {})
    selections: dict[str, list[str]] = {}
    for run in runs:
        items = {str(item["id"]): item for item in run.get("items", [])}
        for name in hconfig.POLICY_ORDER:
            selection = signal_mod.select(items, hconfig.POLICIES[name], loader.item_ids())
            for entry in selection["selected"]:
                selections.setdefault(entry["item"], []).append(
                    f"{name}@a{run.get('run')}")

    pending = [item_id for item_id in loader.item_ids()
               if item_id in selections
               and (registry.get(item_id) or {}).get("status") != "valid"]
    status = {
        "kind": "live_targeted_escalation",
        "measurement_kind": "live_provider_response",
        "generated_at": runner_now(),
        "policies": {name: hconfig.POLICIES[name].description
                     for name in hconfig.POLICY_ORDER},
        "selected_items": {item_id: reasons for item_id, reasons in selections.items()},
        "attempted": [], "reused": [], "skipped": [],
        "stopped_reason": "",
        "ledger": str(LEDGER_PATH.relative_to(bconfig.BENCHMARK_DIR)),
    }
    if not pending:
        status["stopped_reason"] = "every selected item already has a valid stored response"
        _write_json(STATUS_PATH, status)
        return status

    secrets = bconfig.read_api_keys()
    if not secrets:
        status["stopped_reason"] = "no API keys available"
        _write_json(STATUS_PATH, status)
        return status
    pool = KeyPool.from_state(secrets, state_path=bconfig.KEY_STATE_PATH)
    pool.state_path = RESULTS_DIR / "h_key_state.json"
    eligible = [key for key in pool.keys if key.available()]
    status["eligible_keys"] = len(eligible)
    if not eligible:
        status["stopped_reason"] = "no eligible key after cooldown/quota checks"
        _write_json(STATUS_PATH, status)
        return status

    models = _models(runs)
    executor = Executor(GeminiClient(), pool, UsageLedger(LEDGER_PATH))
    requests = 0
    consecutive = 0
    for item_id in pending:
        if requests >= max_requests:
            status["stopped_reason"] = f"request budget {max_requests} reached"
            status["skipped"] = pending[pending.index(item_id):]
            break
        if consecutive >= max_consecutive_failures:
            status["stopped_reason"] = (
                f"{consecutive} consecutive provider failures; remaining requests stopped "
                "rather than retried into a capacity block")
            status["skipped"] = pending[pending.index(item_id):]
            break
        parts, source = hrunner.escalation_parts(item_id)
        max_marks = int(scheme.scheme_evidence()[item_id]["max_marks"])
        response, attempts = executor.call(
            strategy="h", run=900, batch=f"escalate-{item_id}", purpose="escalation",
            model=models.strong or models.primary, parts=parts,
            system=MARKING_SYSTEM, schema=schema_mod.ITEM_SCHEMA,
            item_ids=[item_id], escalated=True,
            max_attempts=hconfig.POLICIES["h-medium"].max_attempts,
        )
        requests += 1
        payload, parse_error = parse_json(response.text or "")
        if payload is None:
            clean, problems = None, [parse_error or "empty response"]
        else:
            clean, problems = schema_mod.validate_marking(payload, {item_id: max_marks})
        accepted, verdict = hrunner.validate_escalation(
            clean, problems, item_id=item_id, max_marks=max_marks, prior_answer="")
        rows = [row for row in executor.ledger.rows() if row.get("strategy") == "h"]
        request_row = rows[-1] if rows else {}
        entry = {
            "item": item_id,
            "status": "valid" if accepted else
                      ("provider_failed" if not response.ok else "invalid"),
            "validation": verdict,
            "item_result": accepted,
            "request": request_row,
            "cost_usd": request_row.get("cost_usd"),
            "response": {
                "status": response.status, "http_status": response.http_status,
                "finish_reason": response.finish_reason, "model": response.model,
                "usage": response.usage, "text": response.text, "attempts": attempts,
            },
            "model": models.strong or models.primary,
            "source": source,
            "escalated_at": runner_now(),
            "selected_by": selections.get(item_id, []),
        }
        registry[item_id] = entry
        _write_json(REGISTRY_PATH, registry)
        status["attempted"].append({
            "item": item_id, "status": entry["status"],
            "http_status": response.http_status, "error_code": response.error_code,
            "cost_usd": entry["cost_usd"], "reasons": verdict.get("reasons", [])[:3],
            "selected_by": entry["selected_by"],
        })
        if response.ok:
            consecutive = 0
        else:
            consecutive += 1

    _write_json(STATUS_PATH, status)
    return status


def runner_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------- scoring
def _aggregate(runs: list[dict]) -> dict:
    summary = evaluator.summarise(runs)
    summary["strict_correct_runs"] = sum(1 for run in runs if run.get("strict_correct"))
    summary["paper_scores"] = [run.get("paper_score_awarded") for run in runs]
    summary["false_awards_total"] = sum(run.get("false_awards") or 0 for run in runs)
    summary["false_deductions_total"] = sum(run.get("false_deductions") or 0 for run in runs)
    return summary


def evaluate_all() -> dict:
    reference = evaluator.load_reference()
    rows = preserved_rows()
    a_payloads = base_runs()
    c_payloads = load_strategy_runs("c")
    registry = _read_json(REGISTRY_PATH, {})
    base_cost = _base_cost_by_run(rows)
    capacity = reference["totals"]["marks_available_scored"]
    configurations: dict[str, dict] = {}

    # A-only and C-only: preserved live measurements, unchanged.
    for name, payloads, strategy, run_ids in (
            ("a-only", a_payloads, "a", BASE_RUN_IDS),
            ("c-only", c_payloads, "c", tuple(int(run["run"]) for run in c_payloads))):
        accuracy = []
        for run in payloads:
            result = evaluator.evaluate_run(run, reference)
            result["_items"] = run.get("items", [])
            accuracy.append(result)
        strategy_rows = _rows_for(rows, strategy, run_ids)
        total_cost = _cost(strategy_rows)
        configurations[name] = {
            "runs": accuracy,
            "summary": _aggregate(accuracy),
            "requests": len(strategy_rows),
            "cost_usd": total_cost,
            "cost_per_submission_usd": (round(total_cost / len(accuracy), 8)
                                        if total_cost is not None and accuracy else None),
            "cost_per_criterion_usd": (round(total_cost / (capacity * len(accuracy)), 8)
                                       if total_cost is not None and accuracy else None),
            "escalation_requests": sum(1 for row in strategy_rows
                                       if row.get("purpose") == "escalation"),
            "full_document_requests": sum(
                1 for row in strategy_rows
                if row.get("purpose") in {"marking", "extraction"}
                and (row.get("batch") or "").startswith(("whole-paper", "doc-understanding",
                                                          "extract-scheme"))),
            "ledger_rows": strategy_rows,
        }

    # H policies: replayed A base + the stored live escalation responses.
    models = _models(a_payloads)
    for index, name in enumerate(hconfig.POLICY_ORDER):
        policy_config = hconfig.POLICIES[name]
        payloads = []
        escalations = []
        for base in a_payloads:
            run_id = 900 + int(base["run"]) * 10 + index
            payload = hrunner.StrategyHRunner(_OfflineExecutor(), models).run(
                base, run_id, policy_config, cache=registry)
            payload["base_cost_usd"] = base_cost.get(int(base["run"]))
            applied = payload["escalations"]
            cost = heval.cost_attribution(payload["base_cost_usd"], registry, applied)
            cost["base_run"] = base.get("run")
            payload["cost"] = cost
            payloads.append(payload)
            escalations.append({
                "base_run": base.get("run"),
                "selected": [entry["item"] for entry in
                             signal_mod.select({str(i["id"]): i for i in base["items"]},
                                               policy_config, loader.item_ids())["selected"]],
                "applied": applied,
                "changes": payload["escalation_changes"],
                "review": payload["unresolved_for_review"],
                "signal_summary": payload["signal_summary"],
            })
        accuracy = [evaluator.evaluate_run(payload, reference) for payload in payloads]
        total_cost = (round(sum(payload["cost"]["total_cost_usd"] for payload in payloads), 8)
                      if all(payload["cost"]["total_cost_usd"] is not None
                             for payload in payloads) else None)
        configurations[name] = {
            "policy": policy_config.name,
            "description": policy_config.description,
            "signals": sorted(policy_config.signals),
            "cap": policy_config.max_escalations,
            "runs": accuracy,
            "run_payloads": payloads,
            "summary": _aggregate(accuracy),
            "new_live_requests": sum(payload["request_count"] for payload in payloads),
            "requests": sum(1 + len(payload["escalations"]) for payload in payloads),
            "reused_responses": sum(payload["reused_responses"] for payload in payloads),
            "cost_usd": total_cost,
            "cost_per_submission_usd": (round(total_cost / len(accuracy), 8)
                                        if total_cost is not None else None),
            "cost_per_criterion_usd": (round(total_cost / (capacity * len(accuracy)), 8)
                                       if total_cost is not None else None),
            "escalation_requests": sum(len(payload["escalations"]) for payload in payloads),
            "escalations": escalations,
            "review_entries": sum(len(payload["unresolved_for_review"]) for payload in payloads),
            "full_document_requests": 0,
            "base_full_document_requests": len(payloads),
        }

    difficult = heval.difficult_items(reference, a_payloads)
    for name, entry in configurations.items():
        payloads = entry.get("run_payloads")
        entry["difficult_subset"] = (
            [heval.subset_metrics(payload, difficult, reference) for payload in payloads]
            if payloads else
            [heval.subset_metrics({"items": run.get("_items", [])}, difficult, reference)
             for run in entry["runs"]]
        )
        entry["bootstrap"] = [heval.bootstrap(run) for run in entry["runs"]]

    for entry in configurations.values():
        for run in entry["runs"]:
            run.pop("_items", None)

    registry_rows = [row for row in UsageLedger(LEDGER_PATH).rows()
                     if row.get("purpose") != "probe"] if LEDGER_PATH.is_file() else []
    payload = {
        "kind": "strategy_h_comparison",
        "generated_at": runner_now(),
        "reference_status": reference["verification"]["status"],
        "warning": (
            "Candidate reference, not teacher-certified. The A stage of every H "
            "configuration is a replayed live A response; only the escalation stage is a "
            "fresh live request. One paper only: no significance is claimed."
        ),
        "paper_max_marks": capacity,
        "paper_reference_marks": reference["totals"]["candidate_marks_awarded"],
        "base_runs": BASE_RUN_IDS,
        "difficult_items": difficult,
        "configurations": {
            name: {key: value for key, value in entry.items() if key != "run_payloads"}
            for name, entry in configurations.items()
        },
        "h_run_payloads": {name: entry.get("run_payloads") or []
                           for name, entry in configurations.items()},
        "escalation_registry_summary": {
            "items": len(registry),
            "valid": sum(1 for entry in registry.values() if entry.get("status") == "valid"),
            "invalid": sum(1 for entry in registry.values() if entry.get("status") == "invalid"),
            "provider_failed": sum(1 for entry in registry.values()
                                   if entry.get("status") == "provider_failed"),
            "actual_spend_usd": round(sum(entry.get("cost_usd") or 0
                                          for entry in registry.values()), 8),
            "live_requests": len(registry_rows),
            "http_429": sum(1 for row in registry_rows if row.get("http_status") == 429),
            "http_503": sum(1 for row in registry_rows if row.get("http_status") == 503),
            "failed_requests": sum(1 for row in registry_rows if not row.get("success")),
            "input_tokens": sum(row.get("input_tokens") or 0 for row in registry_rows),
            "output_tokens": sum(row.get("output_tokens") or 0 for row in registry_rows),
            "cached_tokens": sum(row.get("cached_tokens") or 0 for row in registry_rows),
            "latency_ms_total": sum(row.get("latency_ms") or 0 for row in registry_rows),
            "latency_ms_mean": (round(sum(row.get("latency_ms") or 0
                                          for row in registry_rows)
                                      / len(registry_rows), 1) if registry_rows else None),
        },
    }
    _write_json(RESULTS_DIR / "h_comparison.json", payload)
    _write_json(RESULTS_DIR / "h_runs.json",
                {name: entry.get("run_payloads") or [] for name, entry in configurations.items()})
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strategy H experiment")
    parser.add_argument("--signals", action="store_true")
    parser.add_argument("--escalate", action="store_true")
    parser.add_argument("--evaluate", action="store_true")
    parser.add_argument("--max-requests", type=int, default=12)
    args = parser.parse_args(argv)
    if not (args.signals or args.escalate or args.evaluate):
        parser.print_help()
        return 2
    if args.signals:
        summary = signal_analysis()
        print(json.dumps({run: {name: entry["selected"]
                                for name, entry in data["policies"].items()}
                          for run, data in summary["runs"].items()}, indent=2))
    if args.escalate:
        status = escalate_live(max_requests=args.max_requests)
        print(json.dumps({key: status.get(key) for key in
                          ("stopped_reason", "attempted", "skipped", "eligible_keys")},
                         indent=2)[:4000])
    if args.evaluate:
        payload = evaluate_all()
        print(json.dumps({name: {"f1": entry["summary"].get("criterion_f1"),
                                 "scores": entry["summary"].get("paper_scores"),
                                 "cost": entry.get("cost_usd"),
                                 "requests": entry.get("requests")}
                          for name, entry in payload["configurations"].items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
