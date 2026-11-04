"""Deterministic algebraic equivalence checks for strategy C.

The verifier is deliberately conservative: it answers only when both sides
parse as expressions and SymPy can decide equality.  "Unknown" is a real
outcome and causes escalation rather than a guessed mark.
"""

from __future__ import annotations

import re

from sympy import simplify
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

TRANSFORMS = standard_transformations + (implicit_multiplication_application,)

#: Characters that frequently survive OCR/transcription and break parsing.
_CLEAN = str.maketrans({
    "−": "-", "–": "-", "—": "-", "×": "*", "÷": "/",
    "²": "**2", "³": "**3", "⁴": "**4",
    "（": "(", "）": ")", "，": ",", " ": " ",
})


_QUOTED_TERM = re.compile(r"(?P<var>[A-Za-z])(?P<marks>'+|\"+)")


def _repair_quoted_superscripts(value: str) -> str:
    """Repair OCR/transcription placeholders for lost superscript digits.

    A malformed scheme extraction can leave ``x"`` or ``x""`` where the
    printed scheme had a power.  In these polynomial answers, quoted terms of
    the same variable are written in descending degree order.  A doubled
    marker is a cube; the first of two single markers is a cube and the later
    one is a square; a lone single marker is a square.  This is deliberately
    limited to quote runs immediately after a variable, so ordinary text is
    not rewritten.  The repair is a fallback for a bad extraction, not a
    replacement for asking the extractor for explicit ``^2``/``^3`` notation.
    """
    matches: dict[str, list[re.Match]] = {}
    for match in _QUOTED_TERM.finditer(value):
        matches.setdefault(match.group("var"), []).append(match)
    replacements: list[tuple[int, int, str]] = []
    for group in matches.values():
        for rank, match in enumerate(group):
            marks = match.group("marks")
            exponent = 3 if len(marks) > 1 or (len(group) > 1 and rank == 0) else 2
            replacements.append((match.start("marks"), match.end("marks"), f"**{exponent}"))
    for start, end, replacement in sorted(replacements, reverse=True):
        value = value[:start] + replacement + value[end:]
    return value


def normalise(text: str) -> str:
    value = str(text or "").strip()
    value = value.translate(_CLEAN)
    value = value.replace("^", "**")
    value = value.replace("\\left", "").replace("\\right", "")
    value = re.sub(r"\$+", "", value)
    value = re.sub(r"\s+", "", value)
    value = value.replace("′", "'").replace("″", '"')
    value = _repair_quoted_superscripts(value)
    # A leading "y =" or "x =" is an answer label, not part of the expression.
    value = re.sub(r"^[a-zA-Z]\s*=\s*", "", value)
    return value


def equivalent(student: str, expected: str) -> dict:
    """Return {status: equivalent|different|unknown, detail}.

    ``unknown`` covers empty answers, unparseable text and any SymPy failure; a
    caller must not turn it into a mark.
    """
    left_raw, right_raw = normalise(student), normalise(expected)
    if not left_raw or not right_raw:
        return {"status": "unknown", "detail": "empty side", "student": left_raw, "expected": right_raw}
    try:
        left = parse_expr(left_raw, transformations=TRANSFORMS, evaluate=True)
        right = parse_expr(right_raw, transformations=TRANSFORMS, evaluate=True)
    except Exception as error:  # noqa: BLE001 — parsing is best effort
        return {"status": "unknown", "detail": type(error).__name__,
                "student": left_raw, "expected": right_raw}
    try:
        difference = simplify(left - right)
        if difference == 0:
            return {"status": "equivalent", "detail": "simplify(student - expected) = 0"}
        return {"status": "different", "detail": f"difference {difference}"}
    except Exception as error:  # noqa: BLE001
        return {"status": "unknown", "detail": type(error).__name__,
                "student": left_raw, "expected": right_raw}


def needs_escalation(check: dict) -> bool:
    return check["status"] != "equivalent"
