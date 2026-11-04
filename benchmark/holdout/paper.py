"""Paper-scoped loading for holdout papers and the legacy paper-01 candidate.

Every call names its paper.  There is no global selection and no fallback: a missing or
mismatched artifact raises ``PaperError``.  Holdout records are verified against their
certification (file hashes, attested signatures, reference re-derivation); the legacy
paper-01 adapter verifies against the reserved hashes in the frozen manifest and is marked
``holdout_eligible: False`` because that paper is the design paper.
"""

from __future__ import annotations

from pathlib import Path

from . import certification, compatibility, manifest, schemas, store

LEGACY_PAPER_ID = "paper-01"
HOLDOUT_SOURCE = "holdout"
LEGACY_SOURCE = "legacy_candidate"


class PaperError(ValueError):
    """The requested paper is missing, inconsistent or fails verification."""


def _read(workspace: Path, relative: str) -> dict:
    return store.read_json(store.safe_child(workspace, *Path(relative).parts))


def load_paper(paper_id: str, *, root: Path | None = None, papers_dir: Path | None = None,
               allow_legacy: bool = True, verify: bool = True,
               code_root: Path | None = None) -> dict:
    root = Path(root or store.BENCHMARK_DIR)
    if str(paper_id) == LEGACY_PAPER_ID:
        if not allow_legacy:
            raise PaperError("paper-01 is the design paper and cannot be loaded as holdout")
        return _load_legacy(root, verify=verify)
    directory = Path(papers_dir) if papers_dir is not None else root / "holdout" / "papers"
    workspace = store.safe_child(directory, store.validate_paper_id(paper_id))
    return load_workspace(workspace, paper_id=str(paper_id), root=root, verify=verify,
                          code_root=code_root)


def _check_artifact(problems: list[str], workspace: Path, label: str, relative: str,
                    expected: str | None) -> None:
    try:
        path = store.safe_child(workspace, *Path(relative).parts)
    except store.StoreError as error:
        problems.append(f"{label}: {error}")
        return
    if not path.is_file():
        problems.append(f"{label}: {relative} is missing")
        return
    if expected and store.sha256_file(path) != expected:
        problems.append(f"{label}: hash does not match the certification")


def _item_problems(registry: dict, reference: dict) -> list[str]:
    problems: list[str] = []
    registry_items = {str(item["id"]): item for item in registry["items"]}
    ids = [str(item["id"]) for item in registry["items"]]
    if len(ids) != len(set(ids)):
        problems.append("registry has duplicate item ids")
    excluded = {str(entry.get("id")) for entry in reference.get("exclusions") or []}
    reference_items = {str(item["id"]): item for item in reference.get("items") or []
                       if item.get("status") == "scored"}
    if set(reference_items) != set(registry_items) - excluded:
        problems.append("reference scored items do not match the registry minus exclusions")
    for item_id, item in reference_items.items():
        registry_item = registry_items.get(item_id)
        if registry_item is None:
            continue
        if int(item.get("max_marks", -1)) != int(registry_item.get("max_marks", -2)):
            problems.append(f"{item_id}: max_marks differs between registry and reference")
            continue
        criteria = item.get("criteria") or []
        if len(criteria) != int(item["max_marks"]):
            problems.append(f"{item_id}: criterion records do not match max_marks")
        if [str(c.get("code")) for c in criteria] != \
                [str(c.get("code")) for c in registry_item.get("criteria") or []]:
            problems.append(f"{item_id}: criterion codes differ from the registry")
        awarded = sum(1 for criterion in criteria if criterion.get("awarded") is True)
        if awarded != item.get("expected_mark"):
            problems.append(f"{item_id}: expected_mark disagrees with its criteria")
        if awarded > int(item["max_marks"]):
            problems.append(f"{item_id}: award exceeds max_marks")
        if not str(item.get("evidence", "")).strip():
            problems.append(f"{item_id}: evidence is missing")
    for entry in reference.get("exclusions") or []:
        item_id = str(entry.get("id"))
        registry_item = registry_items.get(item_id)
        if registry_item is None:
            problems.append(f"exclusion {item_id}: item is not in the registry")
            continue
        if not str(entry.get("status", "")).startswith("excluded"):
            problems.append(f"exclusion {item_id}: status is not an exclusion")
        if int(entry.get("marks", -1)) != int(registry_item.get("max_marks", -2)):
            problems.append(f"exclusion {item_id}: marks do not match the printed maximum")
    return problems


def load_workspace(workspace: Path, *, paper_id: str | None = None,
                   root: Path | None = None, verify: bool = True,
                   code_root: Path | None = None) -> dict:
    workspace = Path(workspace)
    root = Path(root or store.BENCHMARK_DIR)
    # Frozen code always lives in the benchmark code tree, not in a paper workspace.
    code_root = Path(code_root) if code_root is not None else store.BENCHMARK_DIR
    if not workspace.is_dir():
        raise PaperError(f"{workspace}: paper workspace is missing")
    try:
        registry = _read(workspace, "items.json")
        reference = _read(workspace, "reference.json")
        cert = _read(workspace, "certification.json")
    except (store.StoreError, OSError) as error:
        raise PaperError(f"paper artifacts are unreadable: {error}") from error

    problems: list[str] = []
    requested = str(paper_id or registry.get("paper_id") or "").strip()
    if requested == LEGACY_PAPER_ID:
        raise PaperError("paper-01 cannot be loaded from a holdout workspace")
    if requested != str(registry.get("paper_id")):
        problems.append(f"registry paper_id {registry.get('paper_id')!r} does not match "
                        f"the requested {requested!r}")
    for label, payload in (("reference", reference), ("certification", cert)):
        if str(payload.get("paper_id")) != str(registry.get("paper_id")):
            problems.append(f"{label} paper_id does not match the registry")

    problems.extend(schemas.validate_items_registry(registry))
    problems.extend(schemas.validate_reference_record(reference))
    problems.extend(schemas.validate_certification_record(cert, registry))
    problems.extend(_item_problems(registry, reference))

    sources = cert.get("sources") or {}
    _check_artifact(problems, workspace, "registry", "items.json",
                    (sources.get("registry") or {}).get("sha256"))
    _check_artifact(problems, workspace, "reference", "reference.json",
                    (sources.get("reference") or {}).get("sha256"))

    pages: dict[str, list[dict]] = {"student": [], "scheme": []}
    for role in ("student", "scheme"):
        for record in (sources.get("pages") or {}).get(role) or []:
            relative = str(record.get("path", ""))
            _check_artifact(problems, workspace, f"{role} page", relative,
                            record.get("sha256"))
            pages[role].append({"path": relative, "sha256": record.get("sha256")})
        if not pages[role]:
            problems.append(f"no {role} pages recorded")
    if not problems and verify:
        problems.extend(certification.validate_certification(
            cert, root=workspace, code_root=code_root))

    report = compatibility.report(registry, paper_id=requested)
    if problems:
        raise PaperError("; ".join(sorted(set(problems))))

    provenance = {str(item["id"]): [
        {"criterion": f"{criterion.get('code')}#{index}",
         "award_source": criterion.get("award_source", "unknown")}
        for index, criterion in enumerate(item["criteria"])]
        for item in reference.get("items") or []}
    return {
        "paper_id": requested,
        "source": HOLDOUT_SOURCE,
        "workspace": str(workspace),
        "registry": registry,
        "registry_sha256": store.sha256_file(workspace / "items.json"),
        "reference": reference,
        "reference_sha256": store.sha256_file(workspace / "reference.json"),
        "certification": cert,
        "certification_sha256": store.sha256_file(workspace / "certification.json"),
        "certification_status": cert.get("status"),
        "pages": pages,
        "items": [item for item in reference.get("items") or []
                  if item.get("status") == "scored"],
        "exclusions": reference.get("exclusions") or [],
        "totals": reference.get("totals") or {},
        "provenance": provenance,
        "compatibility": report,
        "scoreable": report["scoreable"],
        "holdout_eligible": cert.get("status") == "attested_pending_approval",
    }


def _legacy_registry(reference: dict) -> dict:
    items = []
    for index, item in enumerate(reference.get("items") or []):
        if item.get("status") != "scored":
            continue
        items.append({
            "id": str(item["id"]),
            "order": index + 1,
            "scheme_page": int(item.get("scheme_page", 1)),
            "student_page": int(item.get("student_page", 1)),
            "scheme_ref": str(item.get("scheme_ref", "")),
            "max_marks": int(item["max_marks"]),
            "criteria": [{"code": str(criterion.get("code", "")),
                          "text": str(criterion.get("text", ""))}
                         for criterion in item.get("criteria") or []],
        })
    return {"paper_id": LEGACY_PAPER_ID, "items": items}


def _load_legacy(root: Path, *, verify: bool) -> dict:
    from ..code import ground_truth

    reference_path = root / "ground_truth" / "paper-01.json"
    if not reference_path.is_file():
        raise PaperError("paper-01 reference is missing")
    reference = store.read_json(reference_path)
    problems = ground_truth.validate(reference)
    manifest_data = manifest.load(root / "holdout" / "holdout_manifest.json")
    reserved = manifest_data.get("reserved_paper") or {}
    if verify:
        if store.sha256_file(reference_path) != reserved.get("reference_sha256"):
            problems.append("paper-01 reference does not match the reserved digest")
        for entry in reserved.get("page_hashes") or []:
            relative = Path(str(entry.get("path", "")).replace("\\", "/"))
            path = root / relative
            if not path.is_file():
                problems.append(f"paper-01 page is missing: {entry.get('path')}")
            elif store.sha256_file(path) != entry.get("sha256"):
                problems.append(f"paper-01 page hash changed: {entry.get('path')}")
    if problems:
        raise PaperError("; ".join(sorted(set(problems))))

    registry = _legacy_registry(reference)
    report = compatibility.report(registry, paper_id=LEGACY_PAPER_ID)
    pages = {"student": [], "scheme": []}
    for entry in reserved.get("page_hashes") or []:
        role = str(entry.get("role"))
        if role in pages:
            pages[role].append({"path": str(entry.get("path")),
                                "sha256": entry.get("sha256")})
    provenance = {str(item["id"]): [
        {"criterion": f"{criterion.get('code')}#{index}",
         "award_source": "candidate_reference"}
        for index, criterion in enumerate(item.get("criteria") or [])]
        for item in reference.get("items") or [] if item.get("status") == "scored"}
    return {
        "paper_id": LEGACY_PAPER_ID,
        "source": LEGACY_SOURCE,
        "workspace": str(root),
        "registry": registry,
        "registry_sha256": compatibility.canonical_sha256(registry),
        "reference": reference,
        "reference_sha256": store.sha256_file(reference_path),
        "certification": None,
        "certification_sha256": None,
        "certification_status": "candidate_not_teacher_certified",
        "pages": pages,
        "items": [item for item in reference.get("items") or []
                  if item.get("status") == "scored"],
        "exclusions": reference.get("exclusions") or [],
        "totals": reference.get("totals") or {},
        "provenance": provenance,
        "compatibility": report,
        "scoreable": report["scoreable"],
        "holdout_eligible": False,
    }
