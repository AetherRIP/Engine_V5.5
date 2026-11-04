"""The eight mandatory adversarial cases, plus intake boundary checks."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from benchmark.holdout import agreement, manifest, schemas, sheets, store

_DIGEST_AT_IMPORT = manifest.sha256_file(manifest.MANIFEST_PATH)


def _pair(registry, sheet_factory, flips=()):
    first = sheet_factory(registry, "marker_a", "MARKER_A_01")
    second = sheet_factory(registry, "marker_b", "MARKER_B_01", flips=flips)
    return sheets.pair_items(first, second, registry)


# 1 -------------------------------------------------------------------------------
def test_adv_01_paper_with_24_items_is_rejected(registry_factory, tmp_path,
                                                write_json):
    registry = registry_factory(24)
    problems = schemas.validate_items_registry(registry)
    assert any("at least 25 items" in problem for problem in problems)

    path = write_json(registry, name="items.json")
    with pytest.raises(schemas.SchemaError, match="at least 25 items"):
        schemas.load_items_registry(path)


# 2 -------------------------------------------------------------------------------
def test_adv_02_omitted_disagreement_is_rejected(registry, sheet_factory,
                                                 adjudication_factory):
    records = _pair(registry, sheet_factory, flips={("q4", "A1#0")})
    problems = agreement.validate_adjudication_coverage(
        adjudication_factory(registry, []), records, registry)
    assert any("missing adjudication for q4/A1#0" in problem for problem in problems)


# 3 -------------------------------------------------------------------------------
def test_adv_03_unrelated_adjudication_record_is_rejected(registry, sheet_factory,
                                                          adjudication_factory):
    records = _pair(registry, sheet_factory)
    adjudication = adjudication_factory(
        registry, [{"item": "q5", "criterion": "M1#0", "resolution": "a"}])
    problems = agreement.validate_adjudication_coverage(adjudication, records, registry)
    assert any("no disagreement for q5/M1#0" in problem for problem in problems)


# 4 -------------------------------------------------------------------------------
def test_adv_04_third_resolution_without_marks_is_rejected(registry, sheet_factory,
                                                           adjudication_factory):
    records = _pair(registry, sheet_factory, flips={("q2", "A1#0")})
    adjudication = adjudication_factory(
        registry, [{"item": "q2", "criterion": "A1#0", "resolution": "third"}])
    problems = agreement.validate_adjudication_coverage(adjudication, records, registry)
    assert any("requires third-marker marks" in problem for problem in problems)
    with pytest.raises(agreement.AgreementError, match="third"):
        agreement.resolve_awards(records, adjudication, registry)


# 5 -------------------------------------------------------------------------------
def test_adv_05_page_hash_colliding_with_paper01_is_rejected(tmp_path, workspace,
                                                             monkeypatch):
    reserved = manifest.reserved_page_hashes()
    assert reserved, "paper-01 page hashes must still be available"
    collision = next(iter(reserved))
    monkeypatch.setattr(store, "sha256_file", lambda path: collision)
    source = tmp_path / "page.png"
    source.write_bytes(b"a different paper")
    with pytest.raises(store.StoreError, match="reserved paper-01"):
        store.add_pages(workspace, "student", [source], reserved_hashes=reserved)


# 6 -------------------------------------------------------------------------------
def test_adv_06_modified_certification_fails_verification(tmp_path, workspace,
                                                          registry,
                                                          certification_factory):
    path = workspace / "certification.json"
    store.write_json_atomic(path, certification_factory(registry))
    # This is the map a manifest entry records at build time.
    expected = {"certification.json": store.sha256_file(path)}
    assert store.verify_evidence(workspace, expected)["valid"] is True

    certification = certification_factory(registry)
    certification["agreement"]["criterion_kappa"] = 0.99
    store.write_json_atomic(path, certification, replace=True)
    result = store.verify_evidence(workspace, expected)
    assert result["valid"] is False
    assert any("hash mismatch" in problem for problem in result["problems"])


# 7 -------------------------------------------------------------------------------
def test_adv_07_edited_reference_totals_are_rejected(registry, reference_factory):
    reference = reference_factory(registry)
    reference["totals"]["candidate_marks_awarded"] -= 3
    reference["totals"]["marks_available_scored"] += 2
    problems = schemas.validate_reference_record(reference)
    assert any("totals disagree" in problem for problem in problems)


# 8 -------------------------------------------------------------------------------
def test_adv_08_changed_frozen_digest_blocks_registration(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    frozen = code / "strategy_h.py"
    frozen.write_text("POLICIES = ()\n")
    config = {"files": {"strategy_h.py": store.sha256_file(frozen)}}

    # Registration gate passes while the frozen plan is untouched.
    store.assert_frozen_digests(config, code_root=code)

    frozen.write_text("POLICIES = ('changed',)\n")
    with pytest.raises(store.StoreError, match="changed since pre-registration"):
        store.assert_frozen_digests(config, code_root=code)


# ------------------------------------------------------------------------ boundaries
def test_intake_modules_do_not_import_network_or_providers():
    directory = Path(store.__file__).parent
    pattern = re.compile(r"^\s*(?:import|from)\s+"
                         r"(urllib|requests|httpx|socket|aiohttp|google)",
                         re.MULTILINE)
    for name in ("store.py", "schemas.py", "sheets.py", "agreement.py"):
        text = (directory / name).read_text(encoding="utf-8")
        match = pattern.search(text)
        assert match is None, f"{name} imports {match.group(1) if match else ''}"


def test_frozen_manifest_is_untouched_by_the_suite():
    assert manifest.sha256_file(manifest.MANIFEST_PATH) == _DIGEST_AT_IMPORT
    data = manifest.load()
    assert data["papers"] == []
    assert data["status"] == "blocked_no_certified_papers"
    result = manifest.validate_manifest(data, base_dir=manifest.HOLDOUT_DIR.parent,
                                        check_code=True)
    assert result["valid"] is True
    assert result["certified_papers"] == 0
