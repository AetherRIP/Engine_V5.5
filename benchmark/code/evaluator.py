"""Accuracy evaluation against the candidate criterion-level reference.

Two rules matter more than the arithmetic:

* a missing item is not a correct item — it counts as an error, an unresolved
  question and lost coverage;
* criterion-level agreement is measured, not just the paper total, because two
  engines can reach the same total with different awards.

Everything produced here is *provisional*: the reference is not
teacher-certified.
"""

from __future__ import annotations

import json
import re
from statistics import mean

from . import config, ground_truth


def load_reference() -> dict:
    data = ground_truth.load()
    problems = ground_truth.validate(data)
    if problems:
        raise ValueError("ground truth failed validation: " + "; ".join(problems))
    return data


def evaluate_run(run: dict, reference: dict | None = None) -> dict:
    reference = reference or load_reference()
    gt_items = {item["id"]: item for item in reference["items"] if item["status"] == "scored"}
    produced = {item["id"]: item for item in run.get("items", []) if item.get("id") in gt_items}

    criterion_tp = criterion_fp = criterion_fn = criterion_tn = 0
    exact_items = 0
    abs_errors: list[int] = []
    false_awards = false_deductions = 0
    unresolved: list[str] = []
    hallucination_suspects: list[str] = []
    criterion_rows = []

    for item_id, truth in gt_items.items():
        awarded = int(produced.get(item_id, {}).get("awarded", 0))
        expected = int(truth["expected_mark"])
        if item_id not in produced:
            unresolved.append(item_id)
        elif _is_uncertain(produced[item_id]):
            unresolved.append(item_id)
        abs_errors.append(abs(awarded - expected))
        if awarded == expected:
            exact_items += 1
        false_awards += max(0, awarded - expected)
        false_deductions += max(0, expected - awarded)

        model_criteria = _criteria_by_code(produced.get(item_id, {}).get("criteria", []))
        code_counts: dict[str, int] = {}
        for criterion in truth["criteria"]:
            normalized = _normalize_code(criterion["code"])
            index = code_counts.get(normalized, 0)
            code_counts[normalized] = index + 1
            key = f"{normalized}#{index}"
            model_value = model_criteria.get(key)
            truth_value = bool(criterion["awarded"])
            model_awarded = bool(model_value) if model_value is not None else False
            if truth_value and model_awarded:
                criterion_tp += 1
            elif truth_value and not model_awarded:
                criterion_fn += 1
            elif not truth_value and model_awarded:
                criterion_fp += 1
            else:
                criterion_tn += 1
            criterion_rows.append({"item": item_id, "criterion": key,
                                   "expected": truth_value, "awarded": model_awarded})

        if truth["expected_mark"] == 0 and awarded > 0:
            hallucination_suspects.append(item_id)
        if "blank" in truth["evidence"].lower():
            if awarded > 0 or (produced.get(item_id, {}).get("student_answer") or "").strip():
                hallucination_suspects.append(item_id)

    verification = run.get("verification") or {}
    verification_counts = {}
    for check in verification.values():
        if isinstance(check, dict):
            status = str(check.get("status", "unknown"))
            verification_counts[status] = verification_counts.get(status, 0) + 1
    verification_different = verification_counts.get("different", 0)
    different_ids = {str(item_id) for item_id, check in verification.items()
                     if isinstance(check, dict) and check.get("status") == "different"}
    escalated_ids = {str(item_id) for item_id in (run.get("escalations") or [])}
    escalation_gap = bool(different_ids - escalated_ids)
    escalation_count = len(run.get("escalations") or [])
    total_expected = reference["totals"]["candidate_marks_awarded"]
    total_awarded = sum(int(item.get("awarded", 0)) for item in produced.values())
    precision, recall, f1 = _prf(criterion_tp, criterion_fp, criterion_fn)
    scored_count = len(gt_items)
    completion_status = run.get("completion_status")
    if not completion_status:
        completion_status = ("complete" if len(produced) == scored_count
                             else "incomplete_output")
    return {
        "strategy": run.get("strategy"),
        "run": run.get("run"),
        "items_expected": scored_count,
        "items_returned": len(produced),
        "completion_status": completion_status,
        "coverage": round(len(produced) / scored_count, 4) if scored_count else None,
        "items_exact": exact_items,
        "item_exact_accuracy": round(exact_items / scored_count, 4) if scored_count else None,
        "paper_score_awarded": total_awarded,
        "paper_score_expected": total_expected,
        "score_error": total_awarded - total_expected,
        "exact_paper_score": total_awarded == total_expected and len(produced) == scored_count,
        "mean_absolute_score_error": round(mean(abs_errors), 3) if abs_errors else None,
        "false_awards": false_awards,
        "false_deductions": false_deductions,
        "criterion_precision": precision,
        "criterion_recall": recall,
        "criterion_f1": f1,
        "criterion_counts": {"tp": criterion_tp, "fp": criterion_fp,
                             "fn": criterion_fn, "tn": criterion_tn},
        "criterion_rows": criterion_rows,
        "unresolved_items": unresolved,
        "unresolved_count": len(unresolved),
        "invalid_responses": run.get("invalid_responses", 0),
        "verification_status_counts": verification_counts,
        "verification_different": verification_different,
        "escalation_count": escalation_count,
        "escalation_gap": escalation_gap,
        "hallucination_suspects": sorted(set(hallucination_suspects)),
        "errors": run.get("errors", []),
        "strict_correct": (total_awarded == total_expected
                           and len(produced) == scored_count
                           and not unresolved
                           and run.get("invalid_responses", 0) == 0),
        "near_correct_within_one": abs(total_awarded - total_expected) <= 1
                                   and len(produced) == scored_count,
        "reference_status": reference["verification"]["status"],
    }


def _normalize_code(code: object) -> str:
    """Extract the printed criterion code from a model's label.

    Models sometimes prefix the criterion with the question id ("1a_B1") or
    attach a dependency marker ("M1dep").  Both describe the same printed
    criterion, so the comparison must not fail on formatting alone.
    """
    text = str(code or "").strip().upper().replace("DEP", "")
    match = re.search(r"(M1|M2|A1|A2|B1|B2)", text)
    return match.group(1) if match else text


def _criteria_by_code(criteria: list[dict]) -> dict[str, bool]:
    out: dict[str, bool] = {}
    counts: dict[str, int] = {}
    for criterion in criteria:
        code = _normalize_code(criterion.get("code"))
        if not code:
            continue
        counts[code] = counts.get(code, 0) + 1
        out[f"{code}#{counts[code] - 1}"] = bool(criterion.get("awarded"))
    return out


def _is_uncertain(item: dict) -> bool:
    confidence = item.get("confidence")
    if isinstance(confidence, (int, float)) and confidence < 0.5:
        return True
    flags = " ".join(item.get("flags") or []).lower()
    return "ambig" in flags or "illegib" in flags or "unresolved" in flags


def _prf(tp: int, fp: int, fn: int) -> tuple[float | None, float | None, float | None]:
    # No positive predictions with positives present is a recall failure, not
    # an undefined precision: reporting None would hide the miss.
    precision = tp / (tp + fp) if tp + fp else (0.0 if fn else None)
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision is not None and recall is not None and precision + recall else None)
    return (round(precision, 4) if precision is not None else None,
            round(recall, 4) if recall is not None else None,
            round(f1, 4) if f1 is not None else None)


def summarise(runs: list[dict]) -> dict:
    if not runs:
        return {"runs": 0}
    keys = ("coverage", "item_exact_accuracy", "mean_absolute_score_error",
            "criterion_precision", "criterion_recall", "criterion_f1",
            "false_awards", "false_deductions", "unresolved_count")
    summary = {"runs": len(runs), "strict_correct": sum(1 for run in runs if run["strict_correct"])}
    for key in keys:
        values = [run[key] for run in runs if isinstance(run.get(key), (int, float))]
        summary[key] = round(mean(values), 4) if values else None
    return summary


def write_accuracy(results_by_strategy: dict[str, list[dict]]) -> dict:
    payload = {
        "reference": {
            "status": "candidate_not_teacher_certified",
            "warning": (
                "Accuracy is measured against a scheme-derived candidate reference that no "
                "teacher has certified. Treat every figure as provisional."
            ),
        },
        "strategies": {},
    }
    for strategy, runs in results_by_strategy.items():
        payload["strategies"][strategy] = {
            "runs": runs,
            "summary": summarise(runs),
        }
    config.ensure_dirs()
    (config.RESULTS_DIR / "accuracy.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload
