"""Evaluation helpers for the Strategy H experiment.

Accuracy is always computed by the unchanged ``benchmark.code.evaluator`` so every
configuration is scored by the same code, against the same reference and with the same
exclusions.  This module adds what that evaluator does not provide: cost attribution,
the difficult/ambiguous subset and an item-level bootstrap.
"""

from __future__ import annotations

import random
from statistics import mean

from ...code import evaluator, ground_truth

#: Items where the reference records ambiguity or where A disagreed with it in a
#: current run.  Computed at report time from preserved artefacts, never used to pick
#: escalations.
def difficult_items(reference: dict | None = None,
                    a_runs: list[dict] | None = None) -> list[str]:
    reference = reference or ground_truth.load()
    ids = []
    for item in reference.get("items", []):
        if item.get("status") != "scored":
            continue
        evidence = str(item.get("evidence", "")).lower()
        if item.get("confidence") == "medium" or "ambiguous" in evidence:
            ids.append(str(item["id"]))
    for run in a_runs or []:
        got = {str(item.get("id")): item for item in run.get("items", [])}
        for item in reference.get("items", []):
            if item.get("status") != "scored":
                continue
            awarded = got.get(str(item["id"]), {}).get("awarded")
            if awarded is not None and awarded != item["expected_mark"]:
                ids.append(str(item["id"]))
    return sorted(set(ids), key=lambda value: (len(value), value))


def subset_metrics(run: dict, subset: list[str], reference: dict | None = None) -> dict:
    """Item-level agreement restricted to ``subset`` plus micro criterion P/R/F1."""
    reference = reference or ground_truth.load()
    truth = {str(item["id"]): item for item in reference["items"]
             if item.get("status") == "scored" and str(item["id"]) in set(subset)}
    produced = {str(item.get("id")): item for item in run.get("items", [])}
    exact = 0
    abs_error = 0
    false_awards = false_deductions = 0
    tp = fp = fn = 0
    for item_id, item in truth.items():
        awarded = int(produced.get(item_id, {}).get("awarded", 0))
        expected = int(item["expected_mark"])
        abs_error += abs(awarded - expected)
        exact += awarded == expected
        false_awards += max(0, awarded - expected)
        false_deductions += max(0, expected - awarded)
        model_criteria = evaluator._criteria_by_code(
            produced.get(item_id, {}).get("criteria", []))
        counts: dict[str, int] = {}
        for criterion in item["criteria"]:
            code = evaluator._normalize_code(criterion["code"])
            index = counts.get(code, 0)
            counts[code] = index + 1
            key = f"{code}#{index}"
            model_value = model_criteria.get(key)
            truth_value = bool(criterion["awarded"])
            if truth_value and model_value:
                tp += 1
            elif truth_value and not model_value:
                fn += 1
            elif not truth_value and model_value:
                fp += 1
    precision = tp / (tp + fp) if tp + fp else (0.0 if fn else None)
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision is not None and recall is not None and precision + recall else None)
    return {
        "items": len(truth),
        "names": sorted(truth),
        "items_exact": exact,
        "item_exact_accuracy": round(exact / len(truth), 4) if truth else None,
        "mean_absolute_error": round(abs_error / len(truth), 3) if truth else None,
        "false_awards": false_awards,
        "false_deductions": false_deductions,
        "criterion_precision": round(precision, 4) if precision is not None else None,
        "criterion_recall": round(recall, 4) if recall is not None else None,
        "criterion_f1": round(f1, 4) if f1 is not None else None,
        "criterion_counts": {"tp": tp, "fp": fp, "fn": fn},
    }


def bootstrap(accuracy_run: dict, *, n_boot: int = 2000, seed: int = 20261103) -> dict:
    """Item-level bootstrap for micro criterion F1 and the paper-total error.

    Items are the resampling unit, so this interval describes how the score varies over
    these 38 items.  It is **not** a document-level confidence interval: one paper
    cannot support a claim about other papers.
    """
    rows = accuracy_run.get("criterion_rows") or []
    by_item: dict[str, list[dict]] = {}
    for row in rows:
        by_item.setdefault(str(row["item"]), []).append(row)
    items = sorted(by_item)
    if not items:
        return {"n_items": 0, "n_boot": 0, "f1": None, "score_error": None}

    # ``evaluate_run`` does not retain per-item awards, so the score error is reported as
    # its point value rather than resampled from a proxy.
    point_f1 = accuracy_run.get("criterion_f1")
    point_error = accuracy_run.get("score_error")
    rng = random.Random(seed)
    f1_samples = []
    for _ in range(n_boot):
        sample = [rng.choice(items) for _ in range(len(items))]
        tp = fp = fn = 0
        for item_id in sample:
            for row in by_item[item_id]:
                if row["expected"] and row["awarded"]:
                    tp += 1
                elif row["expected"] and not row["awarded"]:
                    fn += 1
                elif row["awarded"] and not row["expected"]:
                    fp += 1
        precision = tp / (tp + fp) if tp + fp else (0.0 if fn else None)
        recall = tp / (tp + fn) if tp + fn else None
        if precision is None or recall is None or not (precision + recall):
            continue
        f1_samples.append(2 * precision * recall / (precision + recall))
    f1_samples.sort()

    def interval(values: list[float]) -> list[float] | None:
        if not values:
            return None
        low = values[int(0.025 * (len(values) - 1))]
        high = values[int(0.975 * (len(values) - 1))]
        return [round(low, 4), round(high, 4)]

    return {
        "n_items": len(items),
        "n_boot": n_boot,
        "seed": seed,
        "f1_point": point_f1,
        "f1_ci95": interval(f1_samples),
        "f1_samples_mean": round(mean(f1_samples), 4) if f1_samples else None,
        "score_error_point": point_error,
        "score_error_note": (
            "Item-level error is not resampled because the per-item awards are not "
            "retained by the shared evaluator; the point value is reported instead."
        ),
        "interpretation_limit": (
            "Item bootstrap over 38 items of ONE paper; not a document-level interval "
            "and not evidence of significance."
        ),
    }


def cost_attribution(base_cost: float | None, registry: dict, item_ids: list[str]) -> dict:
    """Cost of one H submission: A stage plus the escalations it would issue."""
    escalation_costs = []
    missing = 0
    for item_id in item_ids:
        entry = registry.get(str(item_id)) or {}
        value = entry.get("cost_usd")
        if isinstance(value, (int, float)):
            escalation_costs.append(value)
        else:
            missing += 1
    if base_cost is None or missing:
        total = None
    else:
        total = round(base_cost + sum(escalation_costs), 8)
    return {
        "base_cost_usd": base_cost,
        "escalation_cost_usd": round(sum(escalation_costs), 8) if escalation_costs else 0.0,
        "criterion_costs_missing": missing,
        "total_cost_usd": total,
    }


def comparison_row(name: str, accuracy: dict, cost: dict, requests: int,
                   escalation: dict, runs: int) -> dict:
    return {
        "configuration": name,
        "runs": runs,
        "coverage": accuracy.get("coverage"),
        "item_exact_accuracy": accuracy.get("item_exact_accuracy"),
        "criterion_precision": accuracy.get("criterion_precision"),
        "criterion_recall": accuracy.get("criterion_recall"),
        "criterion_f1": accuracy.get("criterion_f1"),
        "paper_scores": None,
        "mean_absolute_score_error": accuracy.get("mean_absolute_score_error"),
        "false_awards": accuracy.get("false_awards"),
        "false_deductions": accuracy.get("false_deductions"),
        "strict_correct_runs": accuracy.get("strict_correct_runs"),
        "requests": requests,
        "cost_usd": cost.get("total_cost_usd"),
        "cost_per_submission_usd": (round(cost["total_cost_usd"] / runs, 8)
                                    if cost.get("total_cost_usd") is not None and runs else None),
        "cost_per_criterion_usd": None,
        "escalation": escalation,
    }
