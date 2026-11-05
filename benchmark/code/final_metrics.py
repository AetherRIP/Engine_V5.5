"""Band-aware accuracy for the final test.

The human reference is a range, not a point: a human marker can err. Exact
equality to the centre (76) is recorded, but the headline agreement test is
whether the awarded total falls inside the human tolerance band (74-78).

``evaluator.py`` is imported unchanged; this module only adds the band view so
historical paper-01 measurements keep their original meaning.
"""

from __future__ import annotations

from statistics import mean

from . import evaluator


def band_evaluate(run: dict, reference: dict, tolerance: int | None = None) -> dict:
    band = reference.get("reference_range") or {}
    center = int(band.get("center", reference["totals"]["candidate_marks_awarded"]))
    tol = int(tolerance if tolerance is not None else band.get("tolerance_marks", 2))
    accuracy = evaluator.evaluate_run(run, reference)
    total = int(accuracy["paper_score_awarded"])
    full = accuracy["coverage"] == 1.0
    return {
        "strategy": accuracy["strategy"],
        "run": accuracy["run"],
        "paper_score_awarded": total,
        "paper_score_max": reference["totals"]["marks_available_scored"],
        "reference_center": center,
        "reference_band": [center - tol, center + tol],
        "signed_error": total - center,
        "absolute_error": abs(total - center),
        "coverage": accuracy["coverage"],
        "exact_center": total == center and full,
        "within_one": abs(total - center) <= 1 and full,
        "within_band": abs(total - center) <= tol and full,
        "criterion_f1": accuracy["criterion_f1"],
        "criterion_precision": accuracy["criterion_precision"],
        "criterion_recall": accuracy["criterion_recall"],
        "item_exact_accuracy": accuracy["item_exact_accuracy"],
        "false_awards": accuracy["false_awards"],
        "false_deductions": accuracy["false_deductions"],
        "unresolved_count": accuracy["unresolved_count"],
        "completion_status": accuracy["completion_status"],
        "strict_correct": accuracy["strict_correct"],
    }


def summarise_band(rows: list[dict]) -> dict:
    if not rows:
        return {"runs": 0}
    f1 = [row["criterion_f1"] for row in rows if row["criterion_f1"] is not None]
    return {
        "runs": len(rows),
        "exact_center": sum(1 for row in rows if row["exact_center"]),
        "within_one": sum(1 for row in rows if row["within_one"]),
        "within_band": sum(1 for row in rows if row["within_band"]),
        "mean_absolute_error": round(mean(row["absolute_error"] for row in rows), 3),
        "max_absolute_error": max(row["absolute_error"] for row in rows),
        "mean_signed_error": round(mean(row["signed_error"] for row in rows), 3),
        "mean_criterion_f1": round(mean(f1), 4) if f1 else None,
        "total_false_awards": sum(row["false_awards"] for row in rows),
        "total_false_deductions": sum(row["false_deductions"] for row in rows),
        "mean_item_exact_accuracy": (
            round(mean(row["item_exact_accuracy"] for row in rows), 4)
            if all(row["item_exact_accuracy"] is not None for row in rows) else None),
        "unresolved_total": sum(row["unresolved_count"] for row in rows),
    }
