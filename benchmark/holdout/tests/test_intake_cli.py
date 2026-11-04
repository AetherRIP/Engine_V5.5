"""Intake CLI: prerequisites, path safety, dry-run and a full synthetic workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.holdout import agreement, certification, intake, manifest, sheets, store


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _root_with_frozen_files(tmp_path: Path) -> Path:
    root = tmp_path / "benchmark"
    (root / "holdout").mkdir(parents=True)
    data = manifest.load()
    _write(root / "holdout" / "holdout_manifest.json", data)
    for relative in data["frozen_config"]["files"]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((store.BENCHMARK_DIR / relative).read_bytes())
    return root


def test_validate_before_init_is_rejected(tmp_path):
    root = _root_with_frozen_files(tmp_path)
    assert intake.main(["--root", str(root), "validate", "holdout-01"]) == 2


def test_path_traversal_is_rejected(tmp_path, registry, write_json):
    root = _root_with_frozen_files(tmp_path)
    items = write_json(registry, name="items.json")
    assert intake.main(["--root", str(root), "init", "../evil",
                        "--items", str(items), "--topic", "algebra",
                        "--difficulty", "higher", "--marks", "50"]) == 2
    assert not (root / "evil").exists()


def test_full_synthetic_workflow(tmp_path, registry, sheet_factory,
                                 adjudication_factory, signature_factory,
                                 custodian_factory, approval_factory):
    root = _root_with_frozen_files(tmp_path)
    sheet_a = sheet_factory(registry, "marker_a", "MARKER_A_01")
    sheet_b = sheet_factory(registry, "marker_b", "MARKER_B_01")
    adjudication = adjudication_factory(registry, [])
    prepared = sheets.prepare_pair(sheet_a, sheet_b, registry)
    awards = agreement.resolve_awards(
        sheets.pair_items(prepared[0], prepared[1], registry), adjudication, registry)
    audit = [{"item": item_id,
              "recorded_marks": sum(1 for criterion in awards[item_id]["criteria"]
                                    if criterion["awarded"]),
              "audit_marks": sum(1 for criterion in awards[item_id]["criteria"]
                                 if criterion["awarded"]),
              "agrees": True, "note": "re-mark matched"}
             for item_id in adjudication["audit_sample"]]

    items = _write(tmp_path / "registry.json", registry)
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "student.png").write_bytes(b"student-page")
    (pages / "scheme.png").write_bytes(b"scheme-page")
    sheet_a_path = _write(tmp_path / "sheet_a.json", sheet_a)
    sheet_b_path = _write(tmp_path / "sheet_b.json", sheet_b)
    adjudication_path = _write(tmp_path / "adjudication.json", adjudication)
    audit_path = _write(tmp_path / "audit.json", audit)

    assert intake.main(["--root", str(root), "init", "holdout-01",
                        "--items", str(items), "--topic", "algebra",
                        "--difficulty", "higher", "--marks", "50"]) == 0
    assert intake.main(["--root", str(root), "pages", "holdout-01", "--role",
                        "student", "--files", str(pages / "student.png")]) == 0
    assert intake.main(["--root", str(root), "pages", "holdout-01", "--role",
                        "scheme", "--files", str(pages / "scheme.png")]) == 0
    assert intake.main(["--root", str(root), "markers", "holdout-01", "--role",
                        "marker_a", "--marker-id", "MARKER_A_01",
                        "--file", str(sheet_a_path)]) == 0
    assert intake.main(["--root", str(root), "markers", "holdout-01", "--role",
                        "marker_b", "--marker-id", "MARKER_B_01",
                        "--file", str(sheet_b_path)]) == 0
    assert intake.main(["--root", str(root), "adjudicate", "holdout-01",
                        "--file", str(adjudication_path)]) == 0
    assert intake.main(["--root", str(root), "build", "holdout-01",
                        "--audit", str(audit_path)]) == 0

    workspace = root / "holdout" / "papers" / "holdout-01"
    draft = store.read_json(workspace / "certification.json")
    for role in certification.REQUIRED_SIGNERS:
        evidence = signature_factory(draft, role)
        path = _write(tmp_path / f"{role}.json", evidence)
        assert intake.main(["--root", str(root), "attest", "holdout-01",
                            "--role", role, "--file", str(path)]) == 0
    custodian = _write(tmp_path / "custodian.json", custodian_factory("holdout-01"))
    assert intake.main(["--root", str(root), "attest", "holdout-01", "--role",
                        "custodian", "--file", str(custodian)]) == 0
    assert intake.main(["--root", str(root), "validate", "holdout-01"]) == 0

    assert intake.main(["--root", str(root), "register", "holdout-01",
                        "--dry-run"]) == 0
    assert not (root / "holdout" / "registrations").exists()
    assert intake.main(["--root", str(root), "register", "holdout-01"]) == 0
    revisions = list((root / "holdout" / "registrations").glob("*/reg-*.json"))
    assert len(revisions) == 1
    revision = store.read_json(revisions[0])
    approval = _write(tmp_path / "approval.json",
                      approval_factory(revision["revision_id"]))
    result = intake.main(["--root", str(root), "promote", "--revision",
                          str(revisions[0]), "--approval", str(approval)])
    assert result == 0
    assert manifest.load(root / "holdout" / "holdout_manifest.json")["papers"] == []
    assert list((root / "holdout" / "manifests").glob("holdout_manifest.*.json"))
