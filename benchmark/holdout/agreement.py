"""Agreement, disagreement and adjudication logic.

The protocol is strict on purpose:

* κ is recomputed by this module from the two raw sheets; a supplied κ value is never
  trusted, so agreement cannot be asserted by editing a field;
* every criterion where the markers differ must have exactly one adjudication record;
* a record for a criterion the markers agreed on is an error, not harmless noise;
* ``third`` needs a complete third-marker item and a rationale;
* resolution is explicit — nothing is silently defaulted.
"""

from __future__ import annotations

import math

from . import manifest, schemas


class AgreementError(ValueError):
    """A disagreement has no valid resolution; the caller must stop, not guess."""


def cohen_kappa(pairs: list[tuple[bool, bool]]) -> float:
    """Cohen's κ over criterion-level binary awards."""
    if not pairs:
        raise AgreementError("cannot compute kappa without criterion pairs")
    total = len(pairs)
    observed = sum(1 for a, b in pairs if a == b) / total
    a_positive = sum(1 for a, _ in pairs if a) / total
    b_positive = sum(1 for _, b in pairs if b) / total
    expected = a_positive * b_positive + (1 - a_positive) * (1 - b_positive)
    if math.isclose(expected, 1.0):
        return 1.0 if math.isclose(observed, 1.0) else 0.0
    return (observed - expected) / (1 - expected)


def agreement_summary(pair_records: list[dict]) -> dict:
    pairs = [(criterion["marker_a"], criterion["marker_b"])
             for record in pair_records for criterion in record["criteria"]]
    if not pairs:
        raise AgreementError("cannot summarise agreement without criteria")
    kappa = cohen_kappa(pairs)
    exact_items = 0
    differences = []
    for record in pair_records:
        total_a = sum(1 for c in record["criteria"] if c["marker_a"])
        total_b = sum(1 for c in record["criteria"] if c["marker_b"])
        exact_items += total_a == total_b
        differences.append(abs(total_a - total_b))
    return {
        "items": len(pair_records),
        "criterion_pairs": len(pairs),
        "criterion_kappa": round(kappa, 4),
        "item_exact_agreement": round(exact_items / len(pair_records), 4),
        "mean_absolute_item_difference": round(sum(differences) / len(differences), 4),
        "disagreements": len(criterion_disagreements(pair_records)),
    }


def criterion_disagreements(pair_records: list[dict]) -> list[dict]:
    out: list[dict] = []
    for record in pair_records:
        for criterion in record["criteria"]:
            if criterion["marker_a"] != criterion["marker_b"]:
                out.append({
                    "item": record["item"],
                    "criterion": criterion["key"],
                    "code": criterion["code"],
                    "marker_a": criterion["marker_a"],
                    "marker_b": criterion["marker_b"],
                    "note_a": criterion.get("note_a", ""),
                    "note_b": criterion.get("note_b", ""),
                })
    return out


def _resolved_records(adjudication: dict, registry: dict) -> dict[tuple[str, str], dict]:
    by_item = {str(item.get("id")): item for item in schemas.registry_items(registry)}
    resolved: dict[tuple[str, str], dict] = {}
    for record in adjudication.get("disagreements") or []:
        item_id = str(record.get("item"))
        item = by_item.get(item_id)
        if item is None:
            continue
        key, problem = schemas.resolve_criterion_key(record.get("criterion"), item)
        if problem or key is None:
            continue
        resolved[(item_id, key)] = record
    return resolved


def validate_adjudication_coverage(adjudication: dict, pair_records: list[dict],
                                   registry: dict) -> list[str]:
    """Structural problems plus complete, non-invented coverage of disagreements."""
    problems = schemas.validate_adjudication(adjudication, registry)
    computed = {(record["item"], criterion["key"])
                for record in pair_records
                for criterion in record["criteria"]
                if criterion["marker_a"] != criterion["marker_b"]}
    resolved = _resolved_records(adjudication, registry)

    for pair in sorted(computed - set(resolved)):
        problems.append(f"missing adjudication for {pair[0]}/{pair[1]}")
    for pair in sorted(set(resolved) - computed):
        problems.append(f"no disagreement for {pair[0]}/{pair[1]}")

    exclusions = {str(entry.get("item")): entry
                  for entry in adjudication.get("exclusions") or []}
    third = {str(entry.get("item")): entry
             for entry in adjudication.get("third_marks") or []}

    for (item_id, key), record in sorted(resolved.items()):
        resolution = record.get("resolution")
        if resolution == "third" and item_id not in third:
            problems.append(f"resolution 'third' for {item_id}/{key} requires "
                            "third-marker marks")
        if resolution == "excluded" and item_id not in exclusions:
            problems.append(f"resolution 'excluded' for {item_id}/{key} requires an "
                            "exclusion record")
        if item_id in exclusions and resolution != "excluded":
            problems.append(f"excluded item {item_id} has a resolution {resolution!r} "
                            "that is not 'excluded'")
    return problems


def resolve_awards(pair_records: list[dict], adjudication: dict,
                   registry: dict) -> dict[str, dict]:
    """Return the adjudicated award per item, with provenance for every criterion."""
    resolved = _resolved_records(adjudication, registry)
    exclusions = {str(entry.get("item")): entry
                  for entry in adjudication.get("exclusions") or []}
    third: dict[tuple[str, str], bool] = {}
    for entry in adjudication.get("third_marks") or []:
        item_id = str(entry.get("item"))
        counts: dict[str, int] = {}
        for criterion in entry.get("criteria") or []:
            code = str(criterion.get("code", "")).strip()
            index = counts.get(code, 0)
            counts[code] = index + 1
            third[(item_id, f"{code}#{index}")] = bool(criterion.get("awarded"))

    out: dict[str, dict] = {}
    for record in pair_records:
        item_id = record["item"]
        if item_id in exclusions:
            out[item_id] = {
                "status": f"excluded_{exclusions[item_id].get('reason')}",
                "criteria": [],
            }
            continue
        criteria = []
        for criterion in record["criteria"]:
            key = criterion["key"]
            if criterion["marker_a"] == criterion["marker_b"]:
                award = criterion["marker_a"]
                source = "agreement"
            else:
                entry = resolved.get((item_id, key))
                if entry is None:
                    raise AgreementError(f"unresolved disagreement for {item_id}/{key}")
                resolution = entry.get("resolution")
                if resolution == "a":
                    award, source = criterion["marker_a"], "marker_a"
                elif resolution == "b":
                    award, source = criterion["marker_b"], "marker_b"
                elif resolution == "third":
                    if (item_id, key) not in third:
                        raise AgreementError(
                            f"resolution 'third' for {item_id}/{key} has no "
                            "third-marker award")
                    award, source = third[(item_id, key)], "third"
                else:
                    raise AgreementError(
                        f"{item_id}/{key} resolved {resolution!r} but is not excluded")
            criteria.append({"key": key, "code": criterion["code"],
                             "awarded": bool(award), "source": source})
        out[item_id] = {"status": "scored", "criteria": criteria}
    return out


def audit_sample_status(adjudication: dict, registry: dict) -> dict:
    items = schemas.registry_items(registry)
    required = max(1, int(0.10 * len(items)))
    sample = adjudication.get("audit_sample") or []
    return {"items": len(items), "required": required, "provided": len(sample),
            "valid": len(sample) >= required}


def protocol_kappa_floor() -> float:
    return manifest.MIN_KAPPA
