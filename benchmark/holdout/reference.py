"""Deterministic derivation of a teacher-adjudicated reference record.

The reference is built only from validated human records:

* the custodian's printed item registry,
* two independently submitted marker sheets,
* an adjudication that resolves every disagreement and nothing else.

Every final criterion award keeps its provenance (``award_source``: agreement, marker_a,
marker_b, third), so a reader can see why an award exists without trusting a total.  No
value is inferred: a missing or unresolved award raises instead of defaulting to zero.

The output is deliberately status-honest: it says the reference is adjudicated but not yet
certified.  Certification is a separate artifact that records human signatures.

The record is evaluator-compatible: ``items`` holds the scored items only, each with
``max_marks`` criteria, an ``expected_mark`` equal to the awarded count, and an ``evidence``
string; ``totals.candidate_marks_awarded`` is the number the scorer reads.  Excluded items
are listed in ``exclusions`` and leave the denominator, matching the frozen paper-01
convention.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import agreement, manifest, schemas, sheets, store

DERIVATION_VERSION = 1
REFERENCE_STATUS = "adjudicated_pending_certification"
REFERENCE_SOURCE = ("two independent human marker sheets, criterion-level adjudication; "
                    "certification pending")


class ReferenceError(ValueError):
    """The inputs are inconsistent, so no reference may be produced."""


def canonical_bytes(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n").encode("utf-8")


def canonical_sha256(payload: object) -> str:
    return store.sha256_bytes(canonical_bytes(payload))


def reference_bytes(reference: dict) -> bytes:
    return canonical_bytes(reference)


def reference_sha256(reference: dict) -> str:
    return canonical_sha256(reference)


def write_reference(path: Path, reference: dict, *, replace: bool = False) -> dict:
    """Write the canonical bytes; the file hash is what certification records."""
    return store.write_bytes_atomic(Path(path), reference_bytes(reference),
                                    replace=replace)


def _path(root: Path, relative) -> Path:
    return store.safe_child(Path(root), *Path(str(relative)).parts)


def _load(root: Path, relative) -> dict:
    return store.read_json(_path(root, relative))


def _pii_problems(text: object, where: str) -> list[str]:
    return [f"{where} contains {label}"
            for label in schemas.find_identifying_information(text)]


def _verify_provenance(item_id: str, criterion: dict, pair: dict) -> None:
    source = criterion["source"]
    awarded = bool(criterion["awarded"])
    if source == "agreement":
        if not (pair["marker_a"] == pair["marker_b"] == awarded):
            raise ReferenceError(f"{item_id}/{criterion['key']}: agreement provenance "
                                 "does not match the marker awards")
    elif source == "marker_a":
        if awarded != pair["marker_a"]:
            raise ReferenceError(f"{item_id}/{criterion['key']}: marker_a provenance "
                                 "does not match the marker award")
    elif source == "marker_b":
        if awarded != pair["marker_b"]:
            raise ReferenceError(f"{item_id}/{criterion['key']}: marker_b provenance "
                                 "does not match the marker award")
    elif source != "third":
        raise ReferenceError(f"{item_id}/{criterion['key']}: unknown award source {source!r}")


def _verify_totals(reference: dict) -> None:
    totals = reference["totals"]
    items = reference["items"]
    exclusions = reference["exclusions"]
    available = sum(int(item["max_marks"]) for item in items)
    awarded = sum(int(item["expected_mark"]) for item in items)
    excluded_marks = sum(int(entry["marks"]) for entry in exclusions)
    criteria = sum(len(item["criteria"]) for item in items)
    checks = {
        "marks_available_scored": available,
        "candidate_marks_awarded": awarded,
        "items_scored": len(items),
        "items_excluded": len(exclusions),
        "items_total": len(items) + len(exclusions),
        "excluded_marks": excluded_marks,
        "printed_marks_all_items": available + excluded_marks,
    }
    for key, expected in checks.items():
        if totals.get(key) != expected:
            raise ReferenceError(f"reference total {key}={totals.get(key)!r} does not "
                                 f"match the recomputed {expected}")
    if criteria != available:
        raise ReferenceError("reference criterion count does not match the available marks")
    for item in items:
        counted = sum(1 for criterion in item["criteria"] if criterion["awarded"])
        if counted != item["expected_mark"]:
            raise ReferenceError(f"{item['id']}: expected_mark disagrees with its criteria")
        if counted > item["max_marks"]:
            raise ReferenceError(f"{item['id']}: award exceeds max_marks")
    if available and totals["candidate_percentage"] != round(100 * awarded / available, 2):
        raise ReferenceError("reference candidate_percentage is inconsistent")


def derive_reference(*, registry: dict, sheet_a: dict, sheet_b: dict,
                     adjudication: dict, title: str | None = None) -> dict:
    """Validate the human records, then derive the reference.  Pure and deterministic."""
    problems = schemas.validate_items_registry(registry)
    if problems:
        raise ReferenceError("invalid item registry: " + "; ".join(problems))

    try:
        normal_a, normal_b = sheets.prepare_pair(sheet_a, sheet_b, registry)
    except sheets.SheetError as error:
        raise ReferenceError(str(error)) from error

    pair_records = sheets.pair_items(normal_a, normal_b, registry)
    problems = schemas.validate_adjudication(adjudication, registry)
    problems.extend(agreement.validate_adjudication_coverage(
        adjudication, pair_records, registry))
    if not agreement.audit_sample_status(adjudication, registry)["valid"]:
        problems.append("audit sample is smaller than 10% of the items")
    for entry in adjudication.get("disagreements") or []:
        problems.extend(_pii_problems(entry.get("rationale"), "disagreement rationale"))
    for entry in adjudication.get("exclusions") or []:
        problems.extend(_pii_problems(entry.get("evidence"), "exclusion evidence"))
    if problems:
        raise ReferenceError("; ".join(sorted(set(problems))))

    try:
        awards = agreement.resolve_awards(pair_records, adjudication, registry)
    except agreement.AgreementError as error:
        raise ReferenceError(str(error)) from error

    registry_items = {str(item["id"]): item for item in registry["items"]}
    exclusions = []
    excluded_ids: set[str] = set()
    for entry in adjudication.get("exclusions") or []:
        item_id = str(entry["item"])
        item = registry_items[item_id]
        reason = str(entry["reason"])
        exclusions.append({
            "id": item_id,
            "status": f"excluded_{reason}",
            "reason": reason,
            "max_marks": int(item["max_marks"]),
            "marks": int(item["max_marks"]),
            "evidence": str(entry["evidence"]).strip(),
        })
        excluded_ids.add(item_id)

    pair_index = {(record["item"], criterion["key"]): criterion
                  for record in pair_records for criterion in record["criteria"]}
    items = []
    for item_id, item in registry_items.items():
        if item_id in excluded_ids:
            continue
        resolved = awards.get(item_id)
        if resolved is None or resolved.get("status") != "scored":
            raise ReferenceError(f"{item_id}: no adjudicated award")
        if len(resolved["criteria"]) != int(item["max_marks"]):
            raise ReferenceError(f"{item_id}: resolved criteria do not match max_marks")
        criteria = []
        for criterion, printed in zip(resolved["criteria"], item["criteria"]):
            if criterion["code"] != str(printed["code"]):
                raise ReferenceError(f"{item_id}: criterion order changed during derivation")
            _verify_provenance(item_id, criterion, pair_index[(item_id, criterion["key"])])
            criteria.append({
                "code": criterion["code"],
                "text": str(printed.get("text", "")),
                "awarded": bool(criterion["awarded"]),
                "award_source": criterion["source"],
            })
        awarded = sum(1 for criterion in criteria if criterion["awarded"])
        if awarded > int(item["max_marks"]):
            raise ReferenceError(f"{item_id}: award exceeds max_marks")
        sources = sorted({criterion["award_source"] for criterion in criteria})
        entry = {
            "id": item_id,
            "max_marks": int(item["max_marks"]),
            "criteria": criteria,
            "expected_mark": awarded,
            "status": "scored",
            "confidence": "adjudicated",
            "evidence": (f"{awarded}/{item['max_marks']} criteria awarded; "
                         f"sources: {', '.join(sources)}"),
            "scheme_page": int(item["scheme_page"]),
        }
        if item.get("prompt"):
            entry["prompt"] = str(item["prompt"])
        if item.get("student_page"):
            entry["student_page"] = int(item["student_page"])
        if item.get("scheme_ref"):
            entry["scheme_ref"] = str(item["scheme_ref"])
        items.append(entry)

    available = sum(item["max_marks"] for item in items)
    awarded_total = sum(item["expected_mark"] for item in items)
    excluded_marks = sum(exclusion["marks"] for exclusion in exclusions)
    summary = agreement.agreement_summary(pair_records)
    reference = {
        "paper_id": str(registry["paper_id"]),
        "title": str(title or registry.get("title") or registry["paper_id"]),
        "reference_source": REFERENCE_SOURCE,
        "verification": {
            "status": REFERENCE_STATUS,
            "verified_by": [str(adjudication["adjudicator"])],
            "verified_on": str(adjudication["signed_on"]),
            "warning": ("Adjudicated from two independent human marker sheets. Not yet "
                        "certified: no accuracy figure may be reported until the "
                        "certification artifact is attested."),
        },
        "totals": {
            "items_total": len(items) + len(exclusions),
            "items_scored": len(items),
            "items_excluded": len(exclusions),
            "marks_available_scored": available,
            "candidate_marks_awarded": awarded_total,
            "candidate_percentage": (round(100 * awarded_total / available, 2)
                                     if available else 0.0),
            "printed_marks_all_items": available + excluded_marks,
            "excluded_marks": excluded_marks,
        },
        "items": items,
        "exclusions": exclusions,
        "derivation": {
            "version": DERIVATION_VERSION,
            "criterion_kappa": summary["criterion_kappa"],
            "audit_sample": len(adjudication.get("audit_sample") or []),
        },
    }
    _verify_totals(reference)
    problems = schemas.validate_reference_record(reference)
    if problems:
        raise ReferenceError("derived reference is invalid: " + "; ".join(problems))
    return reference


def derive_from_paths(root: Path, *, registry_path, sheet_paths: dict,
                      adjudication_path, title: str | None = None) -> dict:
    """Re-derive from stored files, used to prove a reference still matches its inputs."""
    raw = {}
    for role in ("marker_a", "marker_b"):
        value = sheet_paths.get(role)
        relative = value.get("raw") if isinstance(value, dict) else value
        if not relative:
            raise ReferenceError(f"{role}: raw marker sheet path is missing")
        raw[role] = _load(root, relative)
    return derive_reference(
        registry=_load(root, registry_path),
        sheet_a=raw["marker_a"],
        sheet_b=raw["marker_b"],
        adjudication=_load(root, adjudication_path),
        title=title,
    )


def protocol_status() -> str:
    return REFERENCE_STATUS


def kappa_floor() -> float:
    return manifest.MIN_KAPPA
