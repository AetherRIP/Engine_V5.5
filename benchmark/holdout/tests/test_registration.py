"""Registration and human-controlled promotion gates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.holdout import (certification, compatibility, manifest, paper,
                               registration, store)


def _register(env, **overrides):
    kwargs = dict(paper_id="holdout-01", topic="algebra", difficulty="higher",
                  marks_available=50)
    kwargs.update(overrides)
    return registration.register(env["workspace"], root=env["root"],
                                 manifest_path=env["manifest"], **kwargs)


def _approve(env, revision, approval_factory, **overrides):
    approval = approval_factory(revision["revision_id"], **overrides)
    return registration.promote(Path(revision["path"]), approval=approval,
                                root=env["root"], manifest_path=env["manifest"])


@pytest.fixture
def env(tmp_path, registry, sheet_factory, adjudication_factory, certified_paper):
    root = tmp_path / "benchmark"
    (root / "holdout").mkdir(parents=True)
    store.write_json_atomic(root / "holdout" / "holdout_manifest.json",
                            manifest.load())
    workspace = root / "holdout" / "papers" / "holdout-01"
    certified_paper(workspace, registry,
                    sheet_factory(registry, "marker_a", "MARKER_A_01"),
                    sheet_factory(registry, "marker_b", "MARKER_B_01"),
                    adjudication_factory(registry, []))
    return {"root": root, "workspace": workspace,
            "manifest": root / "holdout" / "holdout_manifest.json"}


def test_valid_candidate_creates_immutable_revision(env):
    before = store.sha256_file(env["manifest"])
    revision = _register(env)
    assert revision["status"] == "candidate"
    assert revision["paper_entry"]["status"] == "candidate"
    assert Path(revision["path"]).is_file()
    assert store.sha256_file(env["manifest"]) == before
    assert manifest.load(env["manifest"])["papers"] == []


def test_duplicate_paper_id_is_rejected(env):
    _register(env)
    with pytest.raises(registration.RegistrationError, match="already registered"):
        _register(env)


def test_duplicate_page_hash_across_papers_is_rejected(
        env, registry_factory, sheet_factory, adjudication_factory, certified_paper):
    _register(env)
    registry = registry_factory(25, paper_id="holdout-02")
    certified_paper(env["root"] / "holdout" / "papers" / "holdout-02", registry,
                    sheet_factory(registry, "marker_a", "MARKER_A_02"),
                    sheet_factory(registry, "marker_b", "MARKER_B_02"),
                    adjudication_factory(registry, []))
    with pytest.raises(registration.RegistrationError, match="already registered"):
        registration.register(env["root"] / "holdout" / "papers" / "holdout-02",
                              paper_id="holdout-02", topic="algebra",
                              difficulty="higher", marks_available=50,
                              root=env["root"], manifest_path=env["manifest"])


def test_reserved_paper01_hash_is_rejected():
    problems = registration.page_hash_problems(
        [{"path": "pages/student/p01.png", "sha256": "a" * 64}],
        reserved={"a" * 64}, existing={})
    assert any("reserved paper-01" in problem for problem in problems)


def test_changed_frozen_digest_is_rejected(env, tmp_path):
    with pytest.raises(store.StoreError, match="frozen file missing"):
        _register(env, code_root=tmp_path / "empty")


def test_changed_reference_is_rejected(env):
    path = env["workspace"] / "reference.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["totals"]["candidate_marks_awarded"] -= 1
    store.write_json_atomic(path, data, replace=True)
    with pytest.raises(paper.PaperError):
        _register(env)


def test_invalid_signature_is_rejected(env):
    path = env["workspace"] / "certification.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["signatures"].pop("adjudicator")
    store.write_json_atomic(path, data, replace=True)
    with pytest.raises(paper.PaperError, match="adjudicator"):
        _register(env)


def test_missing_custodian_is_rejected(env):
    (env["workspace"] / "attestations" / "custodian.json").unlink()
    with pytest.raises(registration.RegistrationError, match="custodian"):
        _register(env)


def test_unsupported_criterion_code_is_rejected(
        env, registry_factory, sheet_factory, adjudication_factory, certified_paper):
    registry = registry_factory(25, codes=("C1", "A1"), paper_id="holdout-02")
    workspace = env["root"] / "holdout" / "papers" / "holdout-02"
    certified_paper(workspace, registry,
                    sheet_factory(registry, "marker_a", "MARKER_A_02"),
                    sheet_factory(registry, "marker_b", "MARKER_B_02"),
                    adjudication_factory(registry, []))
    with pytest.raises(compatibility.CompatibilityError, match="C1"):
        registration.register(workspace, paper_id="holdout-02", topic="algebra",
                              difficulty="higher", marks_available=50,
                              root=env["root"], manifest_path=env["manifest"])


def test_candidate_cannot_promote_without_approval(env):
    revision = _register(env)
    with pytest.raises(registration.RegistrationError, match="explicit approval"):
        registration.promote(Path(revision["path"]), approval=None, root=env["root"],
                             manifest_path=env["manifest"])


def test_invalid_approval_evidence_is_rejected(env, approval_factory):
    revision = _register(env)
    with pytest.raises(registration.RegistrationError, match="sha256"):
        _approve(env, revision, approval_factory, evidence_sha256="not-a-hash")


def test_promotion_requires_explicit_approval_and_preserves_history(env,
                                                                   approval_factory):
    revision = _register(env)
    before_manifest = store.sha256_file(env["manifest"])
    before_revision = store.sha256_file(Path(revision["path"]))
    result = _approve(env, revision, approval_factory)
    assert result["papers"][0]["status"] == "certified"
    assert result["status"] == "underpowered_descriptive"
    assert store.sha256_file(env["manifest"]) == before_manifest
    assert store.sha256_file(Path(revision["path"])) == before_revision
    assert Path(result["path"]).is_file()
    assert manifest.validate_manifest(result, base_dir=env["root"],
                                      code_root=store.BENCHMARK_DIR,
                                      check_code=True)["valid"] is True


def test_changed_revision_is_rejected(env, approval_factory):
    revision = _register(env)
    path = Path(revision["path"])
    data = json.loads(path.read_text(encoding="utf-8"))
    data["paper_entry"]["topic"] = "rewritten"
    store.write_json_atomic(path, data, replace=True)
    with pytest.raises(registration.RegistrationError, match="modified"):
        _approve(env, revision, approval_factory)


def test_failed_promotion_leaves_live_manifest_unchanged(env, approval_factory):
    revision = _register(env)
    before = store.sha256_file(env["manifest"])
    with pytest.raises(registration.RegistrationError):
        _approve(env, revision, approval_factory, evidence_sha256="0" * 64)
    assert store.sha256_file(env["manifest"]) == before


def test_promotion_cannot_bypass_certification(env, approval_factory):
    revision = _register(env)
    path = env["workspace"] / "certification.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(registration.RegistrationError, match="certification changed"):
        _approve(env, revision, approval_factory)
