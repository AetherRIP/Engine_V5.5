"""Certification preparation, detached-signature evidence and integrity verification.

The generator produces a *draft*.  It never certifies a paper:

* signatures are supplied as detached SHA-256 hashes of forms the school keeps; the record
  stores the hash and explicitly says identity was not verified;
* ``status`` moves only from ``draft`` to ``attested_pending_approval``, never to
  ``certified``; human registration is the only step that may mark a paper certified;
* a missing signature, audit re-mark or adequate kappa stays in ``pending``, which the
  manifest validator treats as a failure.

Verification is independent of the draft: it re-hashes every recorded artefact, re-checks
the frozen code digests, re-derives the reference from the raw marker sheets, recomputes
kappa and revalidates the audit records.  A hash recorded by this module proves integrity;
it is never presented as proof of signer identity.
"""

from __future__ import annotations

import copy
from pathlib import Path

from . import agreement, manifest, reference as reference_module, schemas, sheets, store

PROTOCOL_VERSION = "holdout-certification/1"
RECORD_VERSION = 1
REQUIRED_SIGNERS = ("marker_a", "marker_b", "adjudicator")
IDENTITY_NOTE = ("The school holds the signed form; this record stores only its SHA-256. "
                 "A hash proves the form's integrity, not the signer's identity.")


class CertificationError(ValueError):
    """Certification inputs are inconsistent or an attestation is missing."""


def _path(root: Path, relative) -> Path:
    return store.safe_child(Path(root), *Path(str(relative)).parts)


def _record(root: Path, relative) -> dict:
    path = _path(root, relative)
    if not path.is_file():
        raise CertificationError(f"{relative}: file is missing")
    record = store.file_record(path, root=Path(root))
    return {"path": record["path"], "sha256": record["sha256"], "bytes": record["bytes"]}


def _expected_signers(certification: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for marker in certification.get("markers") or []:
        role = str(marker.get("role"))
        if role in REQUIRED_SIGNERS:
            out[role] = str(marker.get("id"))
    adjudicator = certification.get("adjudicator") or {}
    if adjudicator.get("id"):
        out["adjudicator"] = str(adjudicator["id"])
    return out


def _pending(certification: dict) -> list[str]:
    signatures = certification.get("signatures") or {}
    pending = [f"signature:{role}" for role in REQUIRED_SIGNERS if role not in signatures]
    block = certification.get("agreement") or {}
    if not block.get("audit_sample_valid"):
        pending.append("audit_sample")
    elif not block.get("audit_complete"):
        pending.append("audit_complete")
    if not block.get("kappa_met"):
        pending.append("criterion_kappa")
    return pending


def _refresh(certification: dict) -> None:
    certification["pending"] = _pending(certification)
    certification["status"] = ("attested_pending_approval" if not certification["pending"]
                               else "draft")


def build_draft(root: Path, *, registry_path, sheet_paths: dict, adjudication_path,
                reference_path, page_paths: dict, audit_evidence, frozen_config: dict,
                title: str | None = None, generated_at: str | None = None,
                code_root: Path | None = None) -> dict:
    """Build an unsigned certification draft from stored, validated inputs."""
    root = Path(root)
    frozen_config = frozen_config or {}
    frozen_files = dict(frozen_config.get("files") or {})
    problems = store.verify_frozen_digests(frozen_config, code_root=code_root)
    if problems:
        raise CertificationError("; ".join(problems))

    registry = store.read_json(_path(root, registry_path))
    problems = schemas.validate_items_registry(registry)
    if problems:
        raise CertificationError("invalid item registry: " + "; ".join(problems))

    raw: dict[str, dict] = {}
    normalised_paths: dict[str, str] = {}
    for role in ("marker_a", "marker_b"):
        value = sheet_paths.get(role)
        if isinstance(value, dict):
            raw_relative = value.get("raw")
            normalised_relative = value.get("normalised")
        else:
            raw_relative = value
            normalised_relative = None
        if not raw_relative or not normalised_relative:
            raise CertificationError(f"{role}: raw and normalised sheet paths are required")
        raw[role] = store.read_json(_path(root, raw_relative))
        normalised_paths[role] = normalised_relative

    try:
        prepared_a, prepared_b = sheets.prepare_pair(raw["marker_a"], raw["marker_b"],
                                                     registry)
    except sheets.SheetError as error:
        raise CertificationError(str(error)) from error
    prepared = {"marker_a": prepared_a, "marker_b": prepared_b}

    marker_sheets = {}
    for role in ("marker_a", "marker_b"):
        stored = store.read_json(_path(root, normalised_paths[role]))
        problems = schemas.validate_marker_sheet(stored, registry, expected_role=role)
        if problems:
            raise CertificationError("; ".join(problems))
        semantic = {key: value for key, value in stored.items()
                    if key != "source_sha256"}
        if reference_module.canonical_sha256(semantic) != \
                reference_module.canonical_sha256(prepared[role]):
            raise CertificationError(
                f"{role}: normalised sheet does not match its raw submission")
        if "source_sha256" in stored:
            raw_digest = store.sha256_file(_path(root, sheet_paths[role]["raw"]))
            if stored["source_sha256"] != raw_digest:
                raise CertificationError(f"{role}: normalised sheet records a different "
                                         "raw hash")
        marker_sheets[role] = {
            "raw": _record(root, sheet_paths[role]["raw"]),
            "normalised": _record(root, normalised_paths[role]),
        }

    adjudication = store.read_json(_path(root, adjudication_path))
    pair_records = sheets.pair_items(prepared_a, prepared_b, registry)
    problems = schemas.validate_adjudication(adjudication, registry)
    problems.extend(agreement.validate_adjudication_coverage(
        adjudication, pair_records, registry))
    if problems:
        raise CertificationError("; ".join(sorted(set(problems))))

    reference_record = _record(root, reference_path)
    reference_data = store.read_json(_path(root, reference_path))
    problems = schemas.validate_reference_record(reference_data)
    if problems:
        raise CertificationError("; ".join(problems))
    derived = reference_module.derive_reference(
        registry=registry, sheet_a=raw["marker_a"], sheet_b=raw["marker_b"],
        adjudication=adjudication, title=title)
    if reference_module.canonical_sha256(derived) != \
            reference_module.canonical_sha256(reference_data):
        raise CertificationError(
            "reference.json does not match a fresh derivation from its inputs")

    pages: dict[str, list[dict]] = {"student": [], "scheme": []}
    reserved = manifest.reserved_page_hashes()
    seen_pages: set[str] = set()
    for role in ("student", "scheme"):
        relatives = page_paths.get(role) or []
        if not relatives:
            raise CertificationError(f"no {role} pages supplied")
        for relative in relatives:
            record = _record(root, relative)
            if record["path"] in seen_pages:
                raise CertificationError(f"{relative}: page is listed twice")
            seen_pages.add(record["path"])
            if record["sha256"] in reserved:
                raise CertificationError(
                    f"{relative}: page hash matches a reserved paper-01 page")
            pages[role].append({**record, "role": role})

    audit_evidence = list(audit_evidence or [])
    audit_problems = schemas.validate_audit_evidence(audit_evidence, adjudication,
                                                     registry)
    audit_status = agreement.audit_sample_status(adjudication, registry)
    summary = agreement.agreement_summary(pair_records)
    kappa_met = summary["criterion_kappa"] >= manifest.MIN_KAPPA
    audit_complete = not audit_problems and audit_status["valid"]

    markers = []
    for role in ("marker_a", "marker_b"):
        sheet = prepared[role]
        markers.append({
            "id": sheet["marker_id"],
            "kind": "human_teacher",
            "role": role,
            "declaration": sheet["declaration"],
            "signed_on": sheet["signed_on"],
            "items_marked": len(sheet["items"]),
        })
    for marker in markers:
        for label in schemas.find_identifying_information(marker["declaration"]):
            raise CertificationError(f"marker declaration contains {label}")
    if title:
        for label in schemas.find_identifying_information(title):
            raise CertificationError(f"title contains {label}")

    exclusions = [{
        "item": str(entry["item"]),
        "reason": entry["reason"],
        "marks": entry["marks"],
        "evidence": entry["evidence"],
        "status": f"excluded_{entry['reason']}",
    } for entry in adjudication.get("exclusions") or []]

    registry_by_id = {str(item["id"]): item for item in registry["items"]}
    pair_index = {(record["item"], criterion["key"]): criterion
                  for record in pair_records for criterion in record["criteria"]}
    disagreements = []
    for entry in adjudication.get("disagreements") or []:
        item_id = str(entry["item"])
        key, problem = schemas.resolve_criterion_key(entry["criterion"],
                                                     registry_by_id[item_id])
        if problem or key is None:
            raise CertificationError(problem or "criterion could not be resolved")
        criterion = pair_index[(item_id, key)]
        disagreements.append({
            "item": item_id,
            "criterion": key,
            "marker_a": bool(criterion["marker_a"]),
            "marker_b": bool(criterion["marker_b"]),
            "resolution": entry["resolution"],
            "resolved_by": entry.get("resolved_by", adjudication["adjudicator"]),
            "rationale": entry["rationale"],
        })

    items_total = len(registry["items"])
    criteria_total = sum(int(item["max_marks"]) for item in registry["items"])
    certification = {
        "protocol_version": PROTOCOL_VERSION,
        "record_version": RECORD_VERSION,
        "paper_id": str(registry["paper_id"]),
        "title": str(title or registry.get("title") or registry["paper_id"]),
        "status": "draft",
        "generated_at": generated_at or store.now_iso(),
        "reference_sha256": reference_record["sha256"],
        "sources": {
            "registry": _record(root, registry_path),
            "pages": pages,
            "marker_sheets": marker_sheets,
            "adjudication": _record(root, adjudication_path),
            "reference": reference_record,
        },
        "frozen": {
            "version": frozen_config.get("version"),
            "files": frozen_files,
            "evaluator_sha256": frozen_files.get("code/evaluator.py"),
            "strategy_files": {key: value for key, value in frozen_files.items()
                               if key.startswith("experimental/strategy_h/")},
        },
        "markers": markers,
        "adjudicator": {
            "id": str(adjudication["adjudicator"]),
            "kind": "human_teacher",
            "signed_on": str(adjudication["signed_on"]),
        },
        "coverage": {
            "items_total": items_total,
            "items_marked_by_both": items_total,
            "criteria_total": criteria_total,
            "items_scored": reference_data["totals"]["items_scored"],
            "items_excluded": len(exclusions),
            "marks_available_scored": reference_data["totals"]["marks_available_scored"],
        },
        "agreement": {
            "criterion_kappa": summary["criterion_kappa"],
            "item_exact_agreement": summary["item_exact_agreement"],
            "mean_absolute_item_difference": summary["mean_absolute_item_difference"],
            "criterion_pairs": summary["criterion_pairs"],
            "kappa_threshold": manifest.MIN_KAPPA,
            "kappa_met": kappa_met,
            "audit_sample": len(audit_evidence),
            "audit_required": audit_status["required"],
            "audit_sample_valid": audit_status["valid"],
            "audit_complete": audit_complete,
            "audit_sample_detail": copy.deepcopy(audit_evidence),
        },
        "disagreements": disagreements,
        "exclusions": exclusions,
        "pending": [],
        "signatures": {},
        "verification": {
            "method": "detached_sha256",
            "identity_verified": False,
            "note": IDENTITY_NOTE,
        },
    }
    _refresh(certification)
    return certification


def apply_signature(certification: dict, evidence: dict) -> dict:
    """Record one detached signature.  Returns a new record; never mutates the input."""
    updated = copy.deepcopy(certification)
    if not isinstance(evidence, dict):
        raise CertificationError("signature evidence must be an object")
    role = str(evidence.get("role", "")).strip()
    expected = _expected_signers(updated)
    if role not in expected and role != "data_custodian":
        raise CertificationError(f"signature role {role!r} is not required or optional "
                                 "for this paper")
    problems = schemas.validate_signature_evidence(
        evidence, expected_role=role or None, expected_signer_id=expected.get(role))
    if role in (updated.get("signatures") or {}):
        problems.append(f"a signature for {role} is already recorded")
    if problems:
        raise CertificationError("; ".join(problems))
    updated.setdefault("signatures", {})[role] = {
        key: evidence[key] for key in ("signer_id", "role", "kind", "signed_on",
                                       "declaration", "form_sha256", "form_location",
                                       "identity_verified")
        if key in evidence}
    if role in {"marker_a", "marker_b"}:
        for marker in updated["markers"]:
            if marker.get("role") == role:
                marker["signature_scan_sha256"] = evidence["form_sha256"]
    _refresh(updated)
    return updated


def _verify_record(root: Path, label: str, record: object) -> list[str]:
    if not isinstance(record, dict):
        return [f"{label}: source record is not an object"]
    relative = record.get("path")
    digest = record.get("sha256")
    if not relative or not digest:
        return [f"{label}: path or sha256 is missing"]
    try:
        path = _path(root, relative)
    except store.StoreError as error:
        return [f"{label}: {error}"]
    if not path.is_file():
        return [f"{label}: file is missing ({relative})"]
    actual = store.sha256_file(path)
    if actual != digest:
        return [f"{label}: hash mismatch (expected {str(digest)[:12]}…, "
                f"found {actual[:12]}…)"]
    return []


def _iter_source_records(certification: dict):
    sources = certification.get("sources") or {}
    for key in ("registry", "adjudication", "reference"):
        if isinstance(sources.get(key), dict):
            yield key, sources[key]
    for role, records in (sources.get("pages") or {}).items():
        for record in records or []:
            yield f"pages.{role}", record
    for role, entry in (sources.get("marker_sheets") or {}).items():
        for kind in ("raw", "normalised"):
            record = (entry or {}).get(kind)
            if isinstance(record, dict):
                yield f"marker_sheets.{role}.{kind}", record


def validate_certification(certification: dict, *, root: Path,
                           code_root: Path | None = None,
                           require_attested: bool = True) -> list[str]:
    """Independently verify a certification record.  Returns every problem found."""
    problems: list[str] = []
    root = Path(root)
    sources = certification.get("sources") or {}
    registry = None
    registry_record = sources.get("registry") or {}
    if registry_record.get("path"):
        try:
            registry = store.read_json(_path(root, registry_record["path"]))
            problems.extend(schemas.validate_items_registry(registry))
        except (store.StoreError, CertificationError) as error:
            problems.append(f"registry source is unusable: {error}")
    problems.extend(schemas.validate_certification_record(certification, registry))

    if require_attested and certification.get("status") != "attested_pending_approval":
        problems.append("certification is not attested; human approval is incomplete")
    if certification.get("pending"):
        problems.append("certification has pending items: "
                        + ", ".join(str(item) for item in certification["pending"]))

    expected = _expected_signers(certification)
    signatures = certification.get("signatures") or {}
    for role, signer in expected.items():
        evidence = signatures.get(role)
        if not isinstance(evidence, dict):
            problems.append(f"missing detached signature evidence for {role}")
            continue
        problems.extend(schemas.validate_signature_evidence(
            evidence, expected_role=role, expected_signer_id=signer))
    for role in signatures:
        if role not in expected and role != "data_custodian":
            problems.append(f"signature for unexpected role {role!r}")

    verification = certification.get("verification") or {}
    if verification.get("identity_verified") is not False:
        problems.append("identity_verified must be false: a detached hash proves "
                        "integrity, not identity")
    if verification.get("method") != "detached_sha256":
        problems.append("verification.method must be detached_sha256")

    for label, record in _iter_source_records(certification):
        problems.extend(_verify_record(root, label, record))

    frozen = certification.get("frozen") or {}
    problems.extend(store.verify_frozen_digests(frozen, code_root=code_root))
    files = frozen.get("files") or {}
    if not files.get("code/evaluator.py"):
        problems.append("frozen evaluator digest is missing")
    elif frozen.get("evaluator_sha256") != files.get("code/evaluator.py"):
        problems.append("frozen evaluator digest is inconsistent")

    reference_record = sources.get("reference") or {}
    adjudication_record = sources.get("adjudication") or {}
    sheet_records = sources.get("marker_sheets") or {}
    if registry_record.get("path") and reference_record.get("path") and \
            adjudication_record.get("path"):
        try:
            derived = reference_module.derive_from_paths(
                root,
                registry_path=registry_record["path"],
                sheet_paths={role: (sheet_records.get(role) or {}).get("raw", {}).get("path")
                             for role in ("marker_a", "marker_b")},
                adjudication_path=adjudication_record["path"],
                title=certification.get("title"))
            loaded = store.read_json(_path(root, reference_record["path"]))
            if reference_module.canonical_sha256(derived) != \
                    reference_module.canonical_sha256(loaded):
                problems.append("reference no longer matches a fresh derivation from "
                                "its inputs")
        except (store.StoreError, CertificationError, reference_module.ReferenceError,
                sheets.SheetError, KeyError, TypeError) as error:
            problems.append(f"reference re-derivation failed: {error}")

    adjudication = None
    if adjudication_record.get("path"):
        try:
            adjudication = store.read_json(_path(root, adjudication_record["path"]))
        except store.StoreError as error:
            problems.append(f"adjudication source is unusable: {error}")

    if registry is not None and adjudication is not None:
        try:
            raw = {role: store.read_json(
                _path(root, (sheet_records.get(role) or {}).get("raw", {}).get("path")))
                for role in ("marker_a", "marker_b")}
            prepared = sheets.prepare_pair(raw["marker_a"], raw["marker_b"], registry)
            summary = agreement.agreement_summary(
                sheets.pair_items(prepared[0], prepared[1], registry))
            recorded = (certification.get("agreement") or {}).get("criterion_kappa")
            if recorded != summary["criterion_kappa"]:
                problems.append("recorded criterion kappa does not match the recomputed "
                                f"{summary['criterion_kappa']}")
            if summary["criterion_kappa"] < manifest.MIN_KAPPA:
                problems.append(f"criterion kappa {summary['criterion_kappa']} is below "
                                f"{manifest.MIN_KAPPA}")
        except (store.StoreError, sheets.SheetError, KeyError, TypeError) as error:
            problems.append(f"kappa could not be recomputed: {error}")

        audit_detail = (certification.get("agreement") or {}).get("audit_sample_detail")
        problems.extend(schemas.validate_audit_evidence(audit_detail, adjudication,
                                                        registry))
        if not (certification.get("agreement") or {}).get("audit_complete"):
            problems.append("audit re-mark evidence is incomplete")

    human_text = {
        "title": certification.get("title", ""),
        "markers": [marker.get("declaration") for marker in
                    certification.get("markers") or []],
        "disagreements": [entry.get("rationale") for entry in
                          certification.get("disagreements") or []],
        "exclusions": [entry.get("evidence") for entry in
                       certification.get("exclusions") or []],
        "audit": [entry.get("note") for entry in
                  (certification.get("agreement") or {}).get("audit_sample_detail") or []],
        "signatures": [entry.get("declaration") for entry in
                       (certification.get("signatures") or {}).values()],
    }
    problems.extend(schemas.scan_payload_for_pii(human_text))
    return sorted(set(problems))


def assert_certification(certification: dict, *, root: Path,
                         code_root: Path | None = None) -> None:
    problems = validate_certification(certification, root=root, code_root=code_root)
    if problems:
        raise CertificationError("; ".join(problems))
