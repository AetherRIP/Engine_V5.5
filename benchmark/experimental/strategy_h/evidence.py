"""Printed-scheme evidence used by the deterministic escalation signals.

This module exposes only what the printed mark scheme says: the question prompt, the
marks available, the printed criterion codes/text and the page numbers.  It never
exposes a reference mark, a reference criterion award or the reference evidence text,
so a strategy cannot read the answer key through it.

The printed accuracy criterion *is* the expected answer (for example
``A1: 2x^3 - 7x^2 - 43x - 42``), so that string is the input to the SymPy equivalence
check.  This is scheme content that every strategy already sees as an image; it is not
a ground-truth award.
"""

from __future__ import annotations

import re
from functools import lru_cache

from ...code import ground_truth

#: Criteria whose code denotes an accuracy answer rather than a method step.
_ACCURACY_CODES = ("A1", "A2", "B1", "B2")

#: Fields copied out of the reference.  Everything else (expected_mark,
#: criteria[].awarded, evidence, confidence) is deliberately dropped.
_ALLOWED = ("id", "prompt", "max_marks", "student_page", "scheme_page")


def _answer_text(criteria: list[dict]) -> str:
    """Return the printed expected answer from the accuracy criterion.

    Falls back to the last printed criterion, which is the accuracy mark on every
    Edexcel-style scheme in this paper.
    """
    for criterion in reversed(criteria):
        code = str(criterion.get("code", "")).upper()
        if any(code.startswith(prefix) for prefix in _ACCURACY_CODES):
            return str(criterion.get("text", "")).strip()
    return str(criteria[-1].get("text", "")).strip() if criteria else ""


def _strip_label(text: str) -> str:
    """Remove a leading label such as ``y =`` from a printed answer."""
    return re.sub(r"^[A-Za-z]\s*=\s*", "", str(text or "").strip())


@lru_cache(maxsize=1)
def scheme_evidence() -> dict[str, dict]:
    """Return ``{item_id: scheme evidence}`` for every scoreable item."""
    data = ground_truth.load()
    evidence: dict[str, dict] = {}
    for item in data.get("items", []):
        if item.get("status") != "scored":
            continue
        criteria = [{"code": str(c.get("code", "")), "text": str(c.get("text", ""))}
                    for c in item.get("criteria") or []]
        entry = {field: item.get(field) for field in _ALLOWED}
        entry["criteria"] = criteria
        entry["expected_answer"] = _strip_label(_answer_text(criteria))
        evidence[str(item["id"])] = entry
    return evidence


def expected_answer(item_id: str) -> str:
    return str((scheme_evidence().get(str(item_id)) or {}).get("expected_answer", ""))


def max_marks(item_id: str) -> int | None:
    value = (scheme_evidence().get(str(item_id)) or {}).get("max_marks")
    return int(value) if isinstance(value, int) else None
