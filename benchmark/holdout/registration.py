"""Immutable paper registration and human-controlled promotion.

Registration produces a *candidate* revision.  It never edits the live manifest and never
marks a paper certified in persisted evidence.  Promotion is a separate, explicitly
approved operation that writes a new manifest revision containing the certified entry; the
input manifest is never overwritten.

Both gates re-run the whole evidence chain: frozen code digests, certification validity,
reference re-derivation, custodian attestation, scoring compatibility, page-hash
disjointness and the full manifest validator (on a projection of the candidate entry).
"""

from __future__ import annotations

import copy
from pathlib import Path

from . import certification, compatibility, manifest, paper, reference, schemas, store

PROTOCOL_VERSION = "holdout-registration/1"
RECORD_VERSION = 1


class RegistrationError(ValueError):
    """A registration or promotion gate failed; no evidence was changed."""


def _manifest_path(root: Path, value) -> Path:
    return Path(value) if value is not None else root / "holdout" / "holdout_manifest.json"


def _registrations_dir(root: Path, value) -> Path:
    return Path(value) if value is not None else root / "holdout" / "registrations"


def _revision_id(paper_id: str, digest: str) -> str:
    return f"reg-{paper_id}-{digest[:12]}"


def page_hash_problems(records: list[dict], *, reserved: set[str],
                       existing: dict[str, str]) -> list[str]:
    problems: list[str] = []
    seen: dict[str, str] = {}
    for record in records:
        digest = str(record.get("sha256"))
        label = str(record.get("path"))
        if digest in reserved:
            problems.append(f"{label}: page hash matches a reserved paper-01 page")
        if digest in existing:
            problems.append(f"{label}: page hash already registered by {existing[digest]}")
        if digest in seen:
            problems.append(f"{label}: duplicate page hash within the paper ({seen[digest]})")
        seen[digest] = label
    return problems


def _existing_page_hashes(manifest_data: dict, registrations_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for paper_entry in manifest_data.get("papers") or []:
        for role, entries in (paper_entry.get("pages") or {}).items():
            for entry in entries or []:
                hashes[str(entry.get("sha256"))] = (
                    f"{paper_entry.get('paper_id')}:{entry.get('path')}")
    if registrations_dir.is_dir():
        for path in sorted(registrations_dir.glob("*/reg-*.json")):
            try:
                revision = store.read_json(path)
            except store.StoreError:
                continue
            entry = revision.get("paper_entry") or {}
            for role, entries in (entry.get("pages") or {}).items():
                for record in entries or []:
                    hashes.setdefault(str(record.get("sha256")),
                                      f"{entry.get('paper_id')} revision")
    return hashes


def _projected_manifest(manifest_data: dict, entry: dict) -> dict:
    projected = copy.deepcopy(manifest_data)
    papers = list(projected.get("papers") or [])
    papers.append({**copy.deepcopy(entry), "status": "certified"})
    projected["papers"] = papers
    certified = sum(1 for item in papers if item.get("status") == "certified")
    projected["status"] = (
        "blocked_no_certified_papers" if certified == 0 else
        "underpowered_descriptive" if certified < manifest.MIN_PAPERS_FOR_DECISION else
        "certified_holdout")
    return projected


def _page_entries(workspace: Path, root: Path, pages: dict) -> dict:
    workspace_rel = workspace.relative_to(root)
    out: dict[str, list[dict]] = {"student": [], "scheme": []}
    for role in ("student", "scheme"):
        for record in pages.get(role) or []:
            relative = (workspace_rel / str(record["path"])).as_posix()
            out[role].append({"path": relative, "sha256": record["sha256"]})
    return out


def _custodian(workspace: Path, paper_id: str) -> dict:
    path = workspace / "attestations" / "custodian.json"
    if not path.is_file():
        raise RegistrationError("custodian attestation is missing")
    attestation = store.read_json(path)
    problems = schemas.validate_custodian_attestation(attestation, paper_id=paper_id)
    if problems:
        raise RegistrationError("; ".join(problems))
    return {"path": path.relative_to(workspace).as_posix(),
            "sha256": store.sha256_file(path), "record": attestation}


def register(workspace: Path, *, paper_id: str, topic: str, difficulty: str,
             marks_available: int, root: Path | None = None, manifest_path=None,
             registrations_dir=None, code_root: Path | None = None,
             dry_run: bool = False) -> dict:
    root = Path(root or store.BENCHMARK_DIR).resolve()
    workspace = Path(workspace).resolve()
    try:
        workspace.relative_to(root)
    except ValueError as error:
        raise RegistrationError("paper workspace must live inside the benchmark root") from error
    manifest_file = _manifest_path(root, manifest_path)
    manifest_data = manifest.load(manifest_file)
    store.assert_frozen_digests(manifest_data.get("frozen_config") or {},
                               code_root=code_root)

    record = paper.load_workspace(workspace, paper_id=paper_id, root=root,
                                  code_root=code_root)
    if record["certification_status"] != "attested_pending_approval":
        raise RegistrationError("certification is not attested; registration is not allowed")
    if not record["scoreable"]:
        compatibility.assert_scoreable(record["compatibility"], paper_id=paper_id)
    if not isinstance(marks_available, int) or marks_available < 1:
        raise RegistrationError("marks_available must be a positive integer")
    if marks_available != int(record["totals"].get("marks_available_scored", -1)):
        raise RegistrationError("marks_available does not match the reference totals")
    if not str(topic).strip() or not str(difficulty).strip():
        raise RegistrationError("topic and difficulty are required")

    custodian = _custodian(workspace, paper_id)
    directory = _registrations_dir(root, registrations_dir)
    existing_ids = {str(entry.get("paper_id")) for entry in manifest_data.get("papers") or []}
    if directory.is_dir():
        existing_ids |= {path.parent.name for path in directory.glob("*/reg-*.json")}
    if paper_id in existing_ids:
        raise RegistrationError(f"paper_id {paper_id!r} is already registered")

    pages = _page_entries(workspace, root, record["pages"])
    all_pages = pages["student"] + pages["scheme"]
    problems = page_hash_problems(all_pages, reserved=manifest.reserved_page_hashes(),
                                  existing=_existing_page_hashes(manifest_data, directory))
    if problems:
        raise RegistrationError("; ".join(problems))

    entry = {
        "paper_id": paper_id,
        "status": "candidate",
        "topic": str(topic),
        "difficulty": str(difficulty),
        "marks_available": marks_available,
        "pages": pages,
        "reference": {"path": (workspace.relative_to(root) / "reference.json").as_posix(),
                      "sha256": record["reference_sha256"]},
        "certification": {
            **{key: copy.deepcopy((record["certification"] or {}).get(key))
               for key in ("markers", "adjudicator", "coverage", "agreement",
                           "disagreements", "exclusions", "pending")},
            "path": (workspace.relative_to(root) / "certification.json").as_posix(),
            "sha256": record["certification_sha256"],
            "status": record["certification_status"],
        },
        "certification_status": record["certification_status"],
        "compatibility": {"scoreable": record["scoreable"],
                          "report_sha256": record["compatibility"]["report_sha256"]},
    }
    projected = _projected_manifest(manifest_data, entry)
    result = manifest.validate_manifest(projected, base_dir=root, code_root=code_root,
                                        check_code=True)
    if not result["valid"]:
        raise RegistrationError("projected manifest is invalid: "
                                + "; ".join(result["problems"]))

    revision = {
        "protocol_version": PROTOCOL_VERSION,
        "record_version": RECORD_VERSION,
        "paper_id": paper_id,
        "status": "candidate",
        "created_at": store.now_iso(),
        "manifest_base_sha256": store.sha256_file(manifest_file),
        "workspace": workspace.relative_to(root).as_posix(),
        "paper_entry": entry,
        "reference_sha256": record["reference_sha256"],
        "certification_sha256": record["certification_sha256"],
        "custodian": custodian,
        "compatibility": record["compatibility"],
        "gate": {"frozen_digests_verified": True,
                 "certification_status": record["certification_status"],
                 "projected_manifest_valid": True},
        "approval": None,
    }
    digest = reference.canonical_sha256(revision)
    revision["content_sha256"] = digest
    revision["revision_id"] = _revision_id(paper_id, digest)

    if not dry_run:
        path = store.safe_child(directory, paper_id, f"{revision['revision_id']}.json")
        try:
            store.write_json_atomic(path, revision, replace=False)
        except store.StoreError as error:
            raise RegistrationError(f"cannot write immutable revision: {error}") from error
        revision["path"] = str(path)
    return revision


def load_revision(path: Path) -> dict:
    revision = store.read_json(path)
    if revision.get("record_version") != RECORD_VERSION:
        raise RegistrationError("unsupported registration revision version")
    body = {key: value for key, value in revision.items()
            if key not in {"content_sha256", "revision_id", "path"}}
    if reference.canonical_sha256(body) != revision.get("content_sha256"):
        raise RegistrationError("registration revision has been modified")
    if revision.get("revision_id") != _revision_id(str(revision.get("paper_id")),
                                                   str(revision["content_sha256"])):
        raise RegistrationError("registration revision id does not match its content")
    return revision


def promote(revision_path: Path, *, approval: dict | None, root: Path | None = None,
            manifest_path=None, output_dir=None, code_root: Path | None = None,
            dry_run: bool = False) -> dict:
    root = Path(root or store.BENCHMARK_DIR).resolve()
    revision_path = Path(revision_path)
    revision = load_revision(revision_path)
    paper_id = str(revision["paper_id"])
    workspace = store.safe_child(root, *Path(revision["workspace"]).parts)
    manifest_file = _manifest_path(root, manifest_path)
    manifest_data = manifest.load(manifest_file)
    problems: list[str] = []

    if store.sha256_file(manifest_file) != revision["manifest_base_sha256"]:
        problems.append("the live manifest changed since this candidate was registered")
    problems.extend(store.verify_frozen_digests(
        manifest_data.get("frozen_config") or {}, code_root=code_root))

    record = paper.load_workspace(workspace, paper_id=paper_id, root=root,
                                  code_root=code_root)
    if record["certification_sha256"] != revision["certification_sha256"]:
        problems.append("certification changed since registration")
    if record["reference_sha256"] != revision["reference_sha256"]:
        problems.append("reference changed since registration")
    if record["compatibility"]["report_sha256"] != \
            revision["compatibility"]["report_sha256"]:
        problems.append("scoring compatibility changed since registration")
    if not record["scoreable"]:
        problems.append("paper is no longer scoreable")
    custodian_path = store.safe_child(workspace, *Path(revision["custodian"]["path"]).parts)
    if not custodian_path.is_file():
        problems.append("custodian attestation is missing")
    elif store.sha256_file(custodian_path) != revision["custodian"]["sha256"]:
        problems.append("custodian attestation changed since registration")
    else:
        custodian = store.read_json(custodian_path)
        problems.extend(schemas.validate_custodian_attestation(custodian,
                                                               paper_id=paper_id))
    problems.extend(schemas.validate_approval_evidence(
        approval, revision_id=str(revision["revision_id"])))
    if problems:
        raise RegistrationError("; ".join(sorted(set(problems))))

    entry = copy.deepcopy(revision["paper_entry"])
    existing = {str(item.get("paper_id")) for item in manifest_data.get("papers") or []}
    if paper_id in existing:
        raise RegistrationError(f"paper_id {paper_id!r} is already in the live manifest")
    projected = _projected_manifest(manifest_data, entry)
    result = manifest.validate_manifest(projected, base_dir=root, code_root=code_root,
                                        check_code=True)
    if not result["valid"]:
        raise RegistrationError("promoted manifest is invalid: "
                                + "; ".join(result["problems"]))

    payload = copy.deepcopy(projected)
    payload["promotion"] = {
        "revision_id": revision["revision_id"],
        "paper_id": paper_id,
        "approver_id": approval["approver_id"],
        "approved_on": approval["approved_on"],
        "approval_sha256": store.sha256_bytes(
            reference.canonical_bytes(approval)),
        "manifest_base_sha256": revision["manifest_base_sha256"],
        "promoted_at": store.now_iso(),
    }
    digest = reference.canonical_sha256(payload)
    payload["manifest_revision_id"] = f"manifest-{digest[:12]}"
    if not dry_run:
        directory = Path(output_dir) if output_dir is not None else root / "holdout" / "manifests"
        path = store.safe_child(directory, f"holdout_manifest.{digest[:12]}.json")
        try:
            store.write_json_atomic(path, payload, replace=False)
        except store.StoreError as error:
            raise RegistrationError(f"cannot write manifest revision: {error}") from error
        payload["path"] = str(path)
    return payload
