"""Explicit criterion-code compatibility for holdout papers.

Schema-valid codes are not automatically scoreable: the frozen evaluator only pairs
``M1/M2/A1/A2/B1/B2`` and silently extracts those substrings from anything else.  This
module classifies every printed code against that real behaviour and blocks evaluation
unless the mapping is exact or an approved dependency alias (``M1dep``).

No mapping is invented, no mark is converted, and no criterion is dropped.  The evaluator
itself is never modified.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..code import evaluator
from . import store

SUPPORTED_CODES = ("M1", "M2", "A1", "A2", "B1", "B2")
_DEPENDENCY_ALIAS = re.compile(r"^(M1|M2|A1|A2|B1|B2)DEP$", re.IGNORECASE)
NORMALISER = "benchmark.code.evaluator._normalize_code"


class CompatibilityError(ValueError):
    """The paper contains codes the frozen scorer cannot pair faithfully."""


def canonical_sha256(payload: object) -> str:
    data = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n").encode("utf-8")
    return store.sha256_bytes(data)


def normalise(code: object) -> str:
    """Use the evaluator's actual normaliser, not a copy of it."""
    return evaluator._normalize_code(code)


def classify(code: object) -> str:
    text = str(code or "").strip()
    if text.upper() in SUPPORTED_CODES:
        return "exact"
    if _DEPENDENCY_ALIAS.match(text):
        return "dependency"
    if normalise(text) in SUPPORTED_CODES:
        return "lossy"
    return "unsupported"


def report(registry: dict, *, paper_id: str | None = None) -> dict:
    """A deterministic, machine-readable compatibility report for one paper."""
    entries: list[dict] = []
    unsupported: list[str] = []
    lossy: list[str] = []
    collisions: list[dict] = []
    total = 0
    for item in registry.get("items") or []:
        by_normalised: dict[str, set[str]] = {}
        for criterion in item.get("criteria") or []:
            code = str(criterion.get("code", "")).strip()
            kind = classify(code)
            normalised = normalise(code)
            total += 1
            entries.append({"item": str(item.get("id")), "code": code,
                            "normalised": normalised, "kind": kind,
                            "supported": kind in {"exact", "dependency"}})
            if kind == "unsupported":
                unsupported.append(code)
            elif kind == "lossy":
                lossy.append(code)
            by_normalised.setdefault(normalised, set()).add(code)
        for normalised, codes in by_normalised.items():
            if len(codes) > 1 and any(classify(code) == "lossy" for code in codes):
                collisions.append({"item": str(item.get("id")),
                                   "normalised": normalised,
                                   "codes": sorted(codes)})
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["code"]] = counts.get(entry["code"], 0) + 1
    codes = [{"code": code, "count": counts[code],
              "normalised": normalise(code), "kind": classify(code),
              "supported": classify(code) in {"exact", "dependency"}}
             for code in sorted(counts)]
    scoreable = not unsupported and not lossy and not collisions
    payload = {
        "paper_id": str(paper_id or registry.get("paper_id")),
        "registry_sha256": canonical_sha256(registry),
        "criteria_total": total,
        "codes": codes,
        "unsupported_codes": sorted(set(unsupported)),
        "lossy_codes": sorted(set(lossy)),
        "collisions": collisions,
        "supported_codes": list(SUPPORTED_CODES),
        "normaliser": NORMALISER,
        "evaluator_sha256": store.sha256_file(Path(evaluator.__file__)),
        "scoreable": scoreable,
    }
    payload["report_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "report_sha256"})
    return payload


def assert_scoreable(report_data: dict, *, paper_id: str | None = None) -> None:
    if report_data.get("scoreable"):
        return
    label = paper_id or report_data.get("paper_id") or "<unknown>"
    reasons = []
    if report_data.get("unsupported_codes"):
        reasons.append("unsupported codes: "
                       + ", ".join(report_data["unsupported_codes"]))
    if report_data.get("lossy_codes"):
        reasons.append("lossy mappings: " + ", ".join(report_data["lossy_codes"]))
    if report_data.get("collisions"):
        reasons.append("mapping collisions: " + ", ".join(
            f"{entry['item']}({'+'.join(entry['codes'])})"
            for entry in report_data["collisions"]))
    raise CompatibilityError(f"{label} is not scoreable: " + "; ".join(reasons))
