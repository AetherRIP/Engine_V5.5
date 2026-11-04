"""Load, validate, pair and preserve marker sheets.

A sheet is a marker's raw submission.  The tool normalises it for comparison but always
keeps the submitted bytes: ``markers/original/<role>.<hash>.json`` is written once and
never replaced.  Re-submitting different content is refused unless the caller asks for it,
and even then the previous normalised copy is archived rather than deleted.
"""

from __future__ import annotations

from pathlib import Path

from . import schemas, store


class SheetError(ValueError):
    """A marker sheet cannot be used; nothing is written when this is raised."""


def load_sheet(path: Path, registry: dict, *, expected_role: str | None = None,
               expected_marker_id: str | None = None) -> dict:
    try:
        data = store.read_json(path)
    except store.StoreError as error:
        raise SheetError(str(error)) from error
    problems = schemas.validate_marker_sheet(
        data, registry, expected_role=expected_role,
        expected_marker_id=expected_marker_id)
    if problems:
        raise SheetError("; ".join(problems))
    return _normalise(data, registry)


def _normalise(sheet: dict, registry: dict) -> dict:
    order = {str(item.get("id")): index for index, item in
             enumerate(schemas.registry_items(registry))}
    items = []
    for item in sorted(sheet["items"], key=lambda entry: order.get(str(entry["id"]), 10**6)):
        criteria = []
        counts: dict[str, int] = {}
        for criterion in item["criteria"]:
            code = str(criterion["code"]).strip()
            index = counts.get(code, 0)
            counts[code] = index + 1
            criteria.append({
                "key": f"{code}#{index}",
                "code": code,
                "awarded": bool(criterion["awarded"]),
                "note": str(criterion.get("note", "")),
            })
        items.append({
            "id": str(item["id"]),
            "criteria": criteria,
            "ambiguous": bool(item.get("ambiguous")),
            "illegible": bool(item.get("illegible")),
            "evidence": str(item.get("evidence", "")),
        })
    return {
        "paper_id": str(sheet["paper_id"]),
        "marker_id": str(sheet["marker_id"]),
        "role": str(sheet["role"]),
        "kind": str(sheet["kind"]),
        "signed_on": str(sheet["signed_on"]),
        "declaration": str(sheet["declaration"]),
        "items": items,
    }


def validate_pair(sheet_a: dict, sheet_b: dict, registry: dict) -> list[str]:
    """A pair is two different teachers marking the same paper independently."""
    problems: list[str] = []
    if sheet_a.get("role") != "marker_a" or sheet_b.get("role") != "marker_b":
        problems.append("sheets must be marker_a and marker_b")
    if sheet_a.get("marker_id") == sheet_b.get("marker_id"):
        problems.append("marker ids must differ; one person cannot certify twice")
    if sheet_a.get("paper_id") != sheet_b.get("paper_id"):
        problems.append("sheets are for different papers")
    if sheet_a.get("paper_id") != str(registry.get("paper_id")):
        problems.append("sheet paper_id does not match the registry")
    return problems


def prepare_pair(sheet_a: dict, sheet_b: dict, registry: dict) -> tuple[dict, dict]:
    """Validate two independent submissions and return them normalised."""
    problems = schemas.validate_marker_sheet(sheet_a, registry)
    problems.extend(schemas.validate_marker_sheet(sheet_b, registry))
    problems.extend(validate_pair(sheet_a, sheet_b, registry))
    if problems:
        raise SheetError("; ".join(problems))
    return (_ensure_normalised(sheet_a, registry),
            _ensure_normalised(sheet_b, registry))


def _ensure_normalised(sheet: dict, registry: dict) -> dict:
    """Accept either a raw submission or an already normalised sheet."""
    criteria = [criterion for item in sheet.get("items") or []
                for criterion in item.get("criteria") or []]
    if criteria and all(isinstance(criterion, dict) and "key" in criterion
                        for criterion in criteria):
        return sheet
    return _normalise(sheet, registry)


def pair_items(sheet_a: dict, sheet_b: dict, registry: dict) -> list[dict]:
    """Align two sheets on the printed registry order, criterion by criterion."""
    sheet_a = _ensure_normalised(sheet_a, registry)
    sheet_b = _ensure_normalised(sheet_b, registry)
    by_a = {item["id"]: item for item in sheet_a["items"]}
    by_b = {item["id"]: item for item in sheet_b["items"]}
    records: list[dict] = []
    for registry_item in schemas.registry_items(registry):
        item_id = str(registry_item["id"])
        if item_id not in by_a or item_id not in by_b:
            raise SheetError(f"sheet pair is missing item {item_id!r}")
        criteria = []
        for criterion_a, criterion_b in zip(by_a[item_id]["criteria"],
                                            by_b[item_id]["criteria"]):
            criteria.append({
                "key": criterion_a["key"],
                "code": criterion_a["code"],
                "marker_a": bool(criterion_a["awarded"]),
                "marker_b": bool(criterion_b["awarded"]),
                "note_a": criterion_a.get("note", ""),
                "note_b": criterion_b.get("note", ""),
            })
        records.append({"item": item_id,
                        "max_marks": int(registry_item["max_marks"]),
                        "criteria": criteria})
    return records


def ingest_sheet(workspace: Path, role: str, source: Path, registry: dict, *,
                 expected_marker_id: str | None = None,
                 replace: bool = False) -> dict:
    """Validate, preserve the raw bytes, then write the normalised sheet."""
    if role not in {"marker_a", "marker_b"}:
        raise SheetError(f"unknown marker role {role!r}")
    sheet = load_sheet(source, registry, expected_role=role,
                       expected_marker_id=expected_marker_id)
    raw = Path(source).read_bytes()
    digest = store.sha256_bytes(raw)

    workspace = Path(workspace)
    original_dir = store.safe_child(workspace, "markers", "original")
    original_dir.mkdir(parents=True, exist_ok=True)
    original = store.safe_child(original_dir, f"{role}.{digest[:12]}.json")
    original_result = store.write_bytes_atomic(original, raw, replace=False)

    normalised_path = store.safe_child(workspace, "markers", f"{role}.json")
    normalised_result = store.write_json_atomic(
        normalised_path, {**sheet, "source_sha256": digest}, replace=replace)

    event = store.append_event(
        workspace, "marker_sheet_ingested", role=role, marker_id=sheet["marker_id"],
        source_sha256=digest, normalised_path=f"markers/{role}.json",
        changed=normalised_result["changed"])
    return {
        "role": role,
        "marker_id": sheet["marker_id"],
        "source_sha256": digest,
        "original": store.file_record(original, root=workspace),
        "normalised": store.file_record(normalised_path, root=workspace),
        "changed": normalised_result["changed"],
        "event": event,
        "sheet": sheet,
    }
