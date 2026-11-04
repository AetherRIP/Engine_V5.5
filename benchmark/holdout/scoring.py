"""Paper-scoped scoring entry point.

The only change from the frozen evaluator is that the reference is passed explicitly from a
verified paper record instead of being loaded from the paper-01 ground truth.  No scoring
semantics are altered; unsupported criterion codes stop the call before scoring.
"""

from __future__ import annotations

from ..code import evaluator
from . import compatibility


class ScoringError(ValueError):
    """The requested paper cannot be scored faithfully."""


def evaluate(paper: dict, run: dict) -> dict:
    if not paper.get("scoreable"):
        compatibility.assert_scoreable(paper.get("compatibility") or {},
                                       paper_id=paper.get("paper_id"))
        raise ScoringError(f"{paper.get('paper_id')}: paper is not scoreable")
    result = evaluator.evaluate_run(run, reference=paper["reference"])
    result["paper_id"] = paper["paper_id"]
    result["source"] = paper.get("source")
    result["reference_sha256"] = paper.get("reference_sha256")
    result["compatibility_sha256"] = (paper.get("compatibility") or {}).get(
        "report_sha256")
    return result
