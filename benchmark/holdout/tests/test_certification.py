"""Certification tests: drafts, detached signatures, tamper detection and approval limits."""

from __future__ import annotations

import json

import pytest

from benchmark.holdout import certification, manifest, schemas, store


def _draft(scenario, **overrides):
    kwargs = dict(scenario["build_kwargs"])
    kwargs.update(overrides)
    return certification.build_draft(scenario["root"], **kwargs)


def _attest(draft, signature_factory):
    for role in certification.REQUIRED_SIGNERS:
        draft = certification.apply_signature(draft, signature_factory(draft, role))
    return draft


def test_draft_is_not_certified(scenario):
    draft = _draft(scenario)
    assert draft["status"] == "draft"
    assert set(draft["pending"]) >= {"signature:marker_a", "signature:marker_b",
                                     "signature:adjudicator"}
    problems = certification.validate_certification(draft, root=scenario["root"])
    assert any("not attested" in problem for problem in problems)
    assert any("missing detached signature evidence" in problem for problem in problems)


def test_attested_certification_validates(scenario, signature_factory):
    record = _attest(_draft(scenario), signature_factory)
    assert record["status"] == "attested_pending_approval"
    assert record["pending"] == []
    assert certification.validate_certification(record, root=scenario["root"]) == []


def test_missing_signature_evidence_blocks(scenario, signature_factory):
    draft = _draft(scenario)
    for role in ("marker_a", "marker_b"):
        draft = certification.apply_signature(draft, signature_factory(draft, role))
    assert draft["pending"] == ["signature:adjudicator"]
    problems = certification.validate_certification(draft, root=scenario["root"])
    assert any("missing detached signature evidence for adjudicator" in problem
               for problem in problems)


@pytest.mark.parametrize("digest, message", [
    ("not-a-hash", "sha256 hex digest"),
    ("0" * 64, "placeholder"),
])
def test_invalid_signature_form_hash_is_rejected(scenario, signature_factory,
                                                 digest, message):
    draft = _draft(scenario)
    with pytest.raises(certification.CertificationError, match=message):
        certification.apply_signature(
            draft, signature_factory(draft, "marker_a", form_sha256=digest))


def test_modified_reference_after_preparation_is_detected(scenario, signature_factory):
    record = _attest(_draft(scenario), signature_factory)
    assert certification.validate_certification(record, root=scenario["root"]) == []

    path = scenario["root"] / "reference.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["totals"]["candidate_marks_awarded"] -= 1
    store.write_json_atomic(path, data, replace=True)

    problems = certification.validate_certification(record, root=scenario["root"])
    assert any("hash mismatch" in problem for problem in problems)
    assert any("no longer matches a fresh derivation" in problem for problem in problems)


def test_modified_marker_sheet_after_preparation_is_detected(scenario,
                                                            signature_factory):
    record = _attest(_draft(scenario), signature_factory)
    path = scenario["root"] / "markers" / "marker_a.raw.json"
    path.write_bytes(path.read_bytes() + b"\n")
    problems = certification.validate_certification(record, root=scenario["root"])
    assert any("marker_sheets.marker_a.raw: hash mismatch" in problem
               for problem in problems)


def test_modified_adjudication_after_preparation_is_detected(scenario,
                                                             signature_factory):
    record = _attest(_draft(scenario), signature_factory)
    path = scenario["root"] / "adjudication.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["audit_sample"] = list(data["audit_sample"]) + ["q3"]
    store.write_json_atomic(path, data, replace=True)
    problems = certification.validate_certification(record, root=scenario["root"])
    assert any("adjudication: hash mismatch" in problem for problem in problems)
    assert any("no longer matches a fresh derivation" in problem for problem in problems)


def test_modified_registry_after_preparation_is_detected(scenario, signature_factory):
    record = _attest(_draft(scenario), signature_factory)
    path = scenario["root"] / "items.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["items"][0]["prompt"] = "A rewritten prompt"
    store.write_json_atomic(path, data, replace=True)
    problems = certification.validate_certification(record, root=scenario["root"])
    assert any("registry: hash mismatch" in problem for problem in problems)
    assert any("no longer matches a fresh derivation" in problem for problem in problems)


def test_changed_frozen_digest_blocks_certification(tmp_path, scenario_factory,
                                                    registry, sheet_factory,
                                                    adjudication_factory,
                                                    signature_factory):
    code_root = tmp_path / "code-root"
    (code_root / "code").mkdir(parents=True)
    (code_root / "experimental" / "strategy_h").mkdir(parents=True)
    evaluator = code_root / "code" / "evaluator.py"
    evaluator.write_text("FROZEN = 1\n")
    strategy = code_root / "experimental" / "strategy_h" / "config.py"
    strategy.write_text("POLICIES = ()\n")
    frozen_config = {"version": "test-v1", "files": {
        "code/evaluator.py": store.sha256_file(evaluator),
        "experimental/strategy_h/config.py": store.sha256_file(strategy),
    }}
    scenario = scenario_factory(
        registry, sheet_factory(registry, "marker_a", "MARKER_A_01"),
        sheet_factory(registry, "marker_b", "MARKER_B_01"),
        adjudication_factory(registry, []), name="frozen")
    draft = certification.build_draft(
        scenario["root"], **{**scenario["build_kwargs"],
                             "frozen_config": frozen_config,
                             "code_root": code_root})
    record = _attest(draft, signature_factory)
    assert certification.validate_certification(
        record, root=scenario["root"], code_root=code_root) == []

    strategy.write_text("POLICIES = ('changed',)\n")
    problems = certification.validate_certification(
        record, root=scenario["root"], code_root=code_root)
    assert any("changed since pre-registration" in problem for problem in problems)


def test_low_kappa_blocks_certification(scenario_factory, registry, sheet_factory,
                                        adjudication_factory, signature_factory):
    flips = {(item["id"], key) for item in registry["items"][:13]
             for key in ("M1#0", "A1#0")}
    sheet_b = sheet_factory(registry, "marker_b", "MARKER_B_01", flips=flips)
    adjudication = adjudication_factory(registry, [
        {"item": item_id, "criterion": key, "resolution": "a"}
        for item_id, key in sorted(flips)])
    scenario = scenario_factory(
        registry, sheet_factory(registry, "marker_a", "MARKER_A_01"),
        sheet_b, adjudication, name="low-kappa")

    draft = _draft(scenario)
    assert draft["agreement"]["criterion_kappa"] < manifest.MIN_KAPPA
    assert draft["agreement"]["kappa_met"] is False

    record = _attest(draft, signature_factory)
    assert record["pending"] == ["criterion_kappa"]
    problems = certification.validate_certification(record, root=scenario["root"])
    assert any("kappa" in problem for problem in problems)


def test_missing_audit_evidence_blocks_certification(scenario, signature_factory):
    draft = _draft(scenario, audit_evidence=[])
    record = _attest(draft, signature_factory)
    assert "audit_complete" in record["pending"]
    problems = certification.validate_certification(record, root=scenario["root"])
    assert any("audit" in problem for problem in problems)


def test_certification_cannot_certify_itself(scenario):
    draft = _draft(scenario)
    problems = schemas.validate_certification_record({**draft, "status": "certified"})
    assert any("human registration" in problem for problem in problems)


def test_identity_is_never_claimed(scenario, signature_factory):
    record = _attest(_draft(scenario), signature_factory)
    assert record["status"] == "attested_pending_approval"
    assert record["verification"]["identity_verified"] is False
    assert "not the signer's identity" in record["verification"]["note"]
    assert certification.validate_certification(record, root=scenario["root"]) == []


def test_identifying_information_in_attestation_is_rejected(scenario,
                                                            signature_factory):
    draft = _draft(scenario)
    with pytest.raises(certification.CertificationError, match="email address"):
        certification.apply_signature(
            draft,
            signature_factory(draft, "marker_a",
                              declaration="Marked by Alice; contact alice@example.com "
                                          "with any questions."))
