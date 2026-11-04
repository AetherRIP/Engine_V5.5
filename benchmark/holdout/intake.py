"""Holdout intake CLI.

Stages: init -> pages -> markers -> adjudicate -> build -> attest -> validate -> register
        -> promote.

The CLI never certifies, promotes implicitly, edits the live manifest, or calls a provider.
Every command refuses to run before its prerequisites, and ``--dry-run`` writes nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import (agreement, certification, compatibility, manifest, paper, reference,
               registration, schemas, sheets, store)


class IntakeError(ValueError):
    """A prerequisite is missing or a command is unsafe."""


def _root(args) -> Path:
    return Path(args.root).resolve()


def _workspace(root: Path, paper_id: str) -> Path:
    return store.safe_child(root / "holdout" / "papers",
                            store.validate_paper_id(paper_id))


def _state(workspace: Path) -> dict:
    path = workspace / "intake.json"
    if not path.is_file():
        raise IntakeError(f"{workspace.name} has not been initialised")
    return store.read_json(path)


def _save(workspace: Path, state: dict) -> None:
    store.write_json_atomic(workspace / "intake.json", state, replace=True)


def _need(state: dict, *steps: str) -> None:
    missing = [step for step in steps if not (state.get("steps") or {}).get(step)]
    if missing:
        raise IntakeError("missing prerequisite step(s): " + ", ".join(missing))


def _raw_sheet(workspace: Path, role: str) -> str:
    paths = sorted((workspace / "markers" / "original").glob(f"{role}.*.json"))
    if len(paths) != 1:
        raise IntakeError(f"{role}: expected exactly one preserved raw sheet, "
                          f"found {len(paths)}")
    return paths[0].relative_to(workspace).as_posix()


def _manifest_data(root: Path) -> dict:
    return manifest.load(root / "holdout" / "holdout_manifest.json")


def cmd_init(args) -> int:
    root = _root(args)
    registry = schemas.load_items_registry(Path(args.items))
    workspace = store.ensure_workspace(args.paper_id,
                                       papers_dir=root / "holdout" / "papers")
    if (workspace / "intake.json").exists():
        raise IntakeError(f"{args.paper_id} is already initialised")
    store.write_json_atomic(workspace / "items.json", registry)
    state = {
        "paper_id": args.paper_id,
        "status": "initialised",
        "topic": args.topic,
        "difficulty": args.difficulty,
        "marks_available": args.marks,
        "title": args.title or args.paper_id,
        "steps": {"init": True},
    }
    _save(workspace, state)
    print(json.dumps({"paper_id": args.paper_id, "workspace": str(workspace)}))
    return 0


def cmd_pages(args) -> int:
    root = _root(args)
    workspace = _workspace(root, args.paper_id)
    state = _state(workspace)
    _need(state, "init")
    records = store.add_pages(workspace, args.role, [Path(item) for item in args.files])
    state["steps"][f"pages_{args.role}"] = True
    state["status"] = "pages"
    _save(workspace, state)
    print(json.dumps({"role": args.role, "records": records}, indent=2))
    return 0


def cmd_markers(args) -> int:
    root = _root(args)
    workspace = _workspace(root, args.paper_id)
    state = _state(workspace)
    _need(state, "pages_student", "pages_scheme")
    registry = store.read_json(workspace / "items.json")
    result = sheets.ingest_sheet(workspace, args.role, Path(args.file), registry,
                                expected_marker_id=args.marker_id)
    state["steps"][f"marker_{args.role}"] = True
    state["status"] = "markers"
    _save(workspace, state)
    print(json.dumps({"role": args.role, "marker_id": result["marker_id"],
                      "sha256": result["source_sha256"]}, indent=2))
    return 0


def cmd_adjudicate(args) -> int:
    root = _root(args)
    workspace = _workspace(root, args.paper_id)
    state = _state(workspace)
    _need(state, "marker_marker_a", "marker_marker_b")
    registry = store.read_json(workspace / "items.json")
    first = sheets.load_sheet(workspace / "markers" / "marker_a.json", registry,
                              expected_role="marker_a")
    second = sheets.load_sheet(workspace / "markers" / "marker_b.json", registry,
                               expected_role="marker_b")
    adjudication = store.read_json(Path(args.file))
    problems = agreement.validate_adjudication_coverage(
        adjudication, sheets.pair_items(first, second, registry), registry)
    if problems:
        raise IntakeError("; ".join(problems))
    store.write_json_atomic(workspace / "adjudication.json", adjudication)
    state["steps"]["adjudication"] = True
    state["status"] = "adjudicated"
    _save(workspace, state)
    print(json.dumps({"adjudication": "stored"}))
    return 0


def cmd_build(args) -> int:
    root = _root(args)
    workspace = _workspace(root, args.paper_id)
    state = _state(workspace)
    _need(state, "adjudication")
    registry = store.read_json(workspace / "items.json")
    adjudication = store.read_json(workspace / "adjudication.json")
    sheet_a = store.read_json(workspace / _raw_sheet(workspace, "marker_a"))
    sheet_b = store.read_json(workspace / _raw_sheet(workspace, "marker_b"))
    audit = store.read_json_value(Path(args.audit))
    reference_data = reference.derive_reference(
        registry=registry, sheet_a=sheet_a, sheet_b=sheet_b,
        adjudication=adjudication, title=state.get("title"))
    reference.write_reference(workspace / "reference.json", reference_data)
    store.write_json_atomic(workspace / "audit.json", audit)
    page_paths = {
        role: [path.relative_to(workspace).as_posix()
               for path in sorted((workspace / "pages" / role).glob("*"))
               if path.is_file()]
        for role in ("student", "scheme")}
    draft = certification.build_draft(
        workspace, registry_path="items.json",
        sheet_paths={role: {"raw": _raw_sheet(workspace, role),
                            "normalised": f"markers/{role}.json"}
                     for role in ("marker_a", "marker_b")},
        adjudication_path="adjudication.json", reference_path="reference.json",
        page_paths=page_paths, audit_evidence=audit,
        frozen_config=_manifest_data(root).get("frozen_config") or {},
        title=state.get("title"), code_root=root)
    store.write_json_atomic(workspace / "certification.json", draft, replace=True)
    state["steps"]["build"] = True
    state["status"] = "built"
    _save(workspace, state)
    print(json.dumps({"reference_sha256": reference.reference_sha256(reference_data),
                      "pending": draft["pending"]}, indent=2))
    return 0


def cmd_attest(args) -> int:
    root = _root(args)
    workspace = _workspace(root, args.paper_id)
    state = _state(workspace)
    _need(state, "build")
    evidence = store.read_json(Path(args.file))
    if args.role == "custodian":
        problems = schemas.validate_custodian_attestation(evidence,
                                                          paper_id=args.paper_id)
        if problems:
            raise IntakeError("; ".join(problems))
        store.write_json_atomic(workspace / "attestations" / "custodian.json", evidence)
    else:
        record = store.read_json(workspace / "certification.json")
        updated = certification.apply_signature(record, evidence)
        store.write_json_atomic(workspace / "certification.json", updated, replace=True)
        store.write_json_atomic(workspace / "attestations" / f"{args.role}.json", evidence)
    state["steps"][f"attest_{args.role}"] = True
    state["status"] = "attested"
    _save(workspace, state)
    print(json.dumps({"role": args.role, "attested": True}))
    return 0


def cmd_validate(args) -> int:
    root = _root(args)
    workspace = _workspace(root, args.paper_id)
    _state(workspace)
    problems: list[str] = []
    try:
        record = paper.load_workspace(workspace, paper_id=args.paper_id, root=root,
                                      code_root=root)
        problems.extend([] if record["scoreable"] else
                        ["paper is not scoreable: "
                         + ", ".join(record["compatibility"]["unsupported_codes"]
                                     + record["compatibility"]["lossy_codes"])])
    except paper.PaperError as error:
        problems.append(str(error))
    custodian_path = workspace / "attestations" / "custodian.json"
    if custodian_path.is_file():
        problems.extend(schemas.validate_custodian_attestation(
            store.read_json(custodian_path), paper_id=args.paper_id))
    else:
        problems.append("custodian attestation is missing")
    result = {"valid": not problems, "problems": sorted(set(problems))}
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


def cmd_register(args) -> int:
    root = _root(args)
    workspace = _workspace(root, args.paper_id)
    state = _state(workspace)
    _need(state, "build", "attest_marker_a", "attest_marker_b", "attest_adjudicator")
    revision = registration.register(
        workspace, paper_id=args.paper_id, topic=state["topic"],
        difficulty=state["difficulty"], marks_available=state["marks_available"],
        root=root, dry_run=args.dry_run)
    state["steps"]["register" if not args.dry_run else "register_dry_run"] = True
    state["status"] = "registered" if not args.dry_run else state["status"]
    _save(workspace, state)
    print(json.dumps({"revision_id": revision["revision_id"],
                      "status": revision["status"],
                      "path": revision.get("path"), "dry_run": args.dry_run}, indent=2))
    return 0


def cmd_promote(args) -> int:
    root = _root(args)
    revision_path = Path(args.revision)
    if not revision_path.is_absolute():
        revision_path = store.safe_child(root, *Path(args.revision).parts)
    approval = store.read_json(Path(args.approval))
    result = registration.promote(revision_path, approval=approval, root=root,
                                  dry_run=args.dry_run)
    print(json.dumps({"manifest_revision_id": result["manifest_revision_id"],
                      "status": result["status"], "path": result.get("path"),
                      "dry_run": args.dry_run}, indent=2))
    return 0


def cmd_status(args) -> int:
    root = _root(args)
    workspace = _workspace(root, args.paper_id)
    print(json.dumps(_state(workspace), indent=2))
    return 0


def cmd_compatibility(args) -> int:
    root = _root(args)
    workspace = _workspace(root, args.paper_id)
    registry = store.read_json(workspace / "items.json")
    print(json.dumps(compatibility.report(registry, paper_id=args.paper_id), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m benchmark.holdout.intake",
        description="Holdout intake: no certification, promotion or live-manifest edits "
                    "happen implicitly.")
    parser.add_argument("--root", default=str(store.BENCHMARK_DIR),
                        help="benchmark root (default: the repository benchmark directory)")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a paper workspace from items.json")
    init.add_argument("paper_id")
    init.add_argument("--items", required=True)
    init.add_argument("--topic", required=True)
    init.add_argument("--difficulty", required=True)
    init.add_argument("--marks", required=True, type=int)
    init.add_argument("--title")
    init.set_defaults(func=cmd_init)

    pages = sub.add_parser("pages", help="add anonymised student or scheme pages")
    pages.add_argument("paper_id")
    pages.add_argument("--role", required=True, choices=["student", "scheme"])
    pages.add_argument("--files", required=True, nargs="+")
    pages.set_defaults(func=cmd_pages)

    markers = sub.add_parser("markers", help="ingest a marker's raw sheet")
    markers.add_argument("paper_id")
    markers.add_argument("--role", required=True, choices=["marker_a", "marker_b"])
    markers.add_argument("--marker-id", required=True)
    markers.add_argument("--file", required=True)
    markers.set_defaults(func=cmd_markers)

    adjudicate = sub.add_parser("adjudicate", help="store the adjudication record")
    adjudicate.add_argument("paper_id")
    adjudicate.add_argument("--file", required=True)
    adjudicate.set_defaults(func=cmd_adjudicate)

    build = sub.add_parser("build", help="derive the reference and certification draft")
    build.add_argument("paper_id")
    build.add_argument("--audit", required=True, help="audit re-mark evidence JSON")
    build.set_defaults(func=cmd_build)

    attest = sub.add_parser("attest", help="record a detached signature or custodian claim")
    attest.add_argument("paper_id")
    attest.add_argument("--role", required=True,
                        choices=["marker_a", "marker_b", "adjudicator", "custodian"])
    attest.add_argument("--file", required=True)
    attest.set_defaults(func=cmd_attest)

    validate = sub.add_parser("validate", help="verify certification, custodian and codes")
    validate.add_argument("paper_id")
    validate.set_defaults(func=cmd_validate)

    register = sub.add_parser("register", help="create an immutable candidate revision")
    register.add_argument("paper_id")
    register.add_argument("--dry-run", action="store_true")
    register.set_defaults(func=cmd_register)

    promote = sub.add_parser("promote", help="promote a candidate with human approval")
    promote.add_argument("--revision", required=True)
    promote.add_argument("--approval", required=True)
    promote.add_argument("--dry-run", action="store_true")
    promote.set_defaults(func=cmd_promote)

    status = sub.add_parser("status", help="show intake state")
    status.add_argument("paper_id")
    status.set_defaults(func=cmd_status)

    compatibility_cmd = sub.add_parser("compatibility",
                                       help="print the criterion-code report")
    compatibility_cmd.add_argument("paper_id")
    compatibility_cmd.set_defaults(func=cmd_compatibility)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (IntakeError, store.StoreError, schemas.SchemaError, sheets.SheetError,
            reference.ReferenceError, certification.CertificationError,
            registration.RegistrationError, paper.PaperError,
            compatibility.CompatibilityError, agreement.AgreementError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
