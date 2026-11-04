"""Marker sheet tests: loading, pairing, coverage and immutable ingestion."""

from __future__ import annotations

import json

import pytest

from benchmark.holdout import sheets, store


def test_load_sheet_returns_keyed_criteria(tmp_path, registry, sheet_factory, write_json):
    path = write_json(sheet_factory(registry, "marker_a", "MARKER_A_01"),
                      name="marker_a.json")
    sheet = sheets.load_sheet(path, registry, expected_role="marker_a")
    assert sheet["items"][0]["criteria"][0]["key"] == "M1#0"
    assert sheet["items"][0]["criteria"][1]["key"] == "A1#0"


def test_load_sheet_rejects_wrong_role(tmp_path, registry, sheet_factory, write_json):
    path = write_json(sheet_factory(registry, "marker_b", "MARKER_B_01"),
                      name="marker_b.json")
    with pytest.raises(sheets.SheetError, match="does not match expected"):
        sheets.load_sheet(path, registry, expected_role="marker_a")


def test_load_sheet_rejects_wrong_marker_id(tmp_path, registry, sheet_factory, write_json):
    path = write_json(sheet_factory(registry, "marker_a", "MARKER_A_01"),
                      name="marker_a.json")
    with pytest.raises(sheets.SheetError, match="does not match expected"):
        sheets.load_sheet(path, registry, expected_role="marker_a",
                          expected_marker_id="MARKER_A_02")


def test_validate_pair_requires_two_people(registry, sheet_factory):
    first = sheet_factory(registry, "marker_a", "MARKER_A_01")
    second = sheet_factory(registry, "marker_b", "MARKER_A_01")
    problems = sheets.validate_pair(first, second, registry)
    assert any("cannot certify twice" in problem for problem in problems)


def test_validate_pair_rejects_swapped_roles(registry, sheet_factory):
    first = sheet_factory(registry, "marker_b", "MARKER_A_01")
    second = sheet_factory(registry, "marker_a", "MARKER_B_01")
    problems = sheets.validate_pair(first, second, registry)
    assert any("must be marker_a and marker_b" in problem for problem in problems)


def test_pair_items_aligns_repeated_codes(registry_factory, sheet_factory):
    registry = registry_factory(25, codes=("M1", "M1", "A1"))
    first = sheet_factory(registry, "marker_a", "MARKER_A_01")
    second = sheet_factory(registry, "marker_b", "MARKER_B_01",
                           flips={("q1", "M1#1")})
    records = sheets.pair_items(first, second, registry)
    assert [criterion["key"] for criterion in records[0]["criteria"]] == [
        "M1#0", "M1#1", "A1#0"]
    assert records[0]["criteria"][1]["marker_a"] is True
    assert records[0]["criteria"][1]["marker_b"] is False


def test_ingest_sheet_preserves_original_bytes(tmp_path, workspace, registry,
                                               sheet_factory):
    source = tmp_path / "submission.json"
    raw = json.dumps(sheet_factory(registry, "marker_a", "MARKER_A_01"),
                     indent=3).encode("utf-8")
    source.write_bytes(raw)
    result = sheets.ingest_sheet(workspace, "marker_a", source, registry,
                                 expected_marker_id="MARKER_A_01")
    assert result["source_sha256"] == store.sha256_bytes(raw)
    originals = list((workspace / "markers" / "original").glob("marker_a.*.json"))
    assert len(originals) == 1
    assert originals[0].read_bytes() == raw
    assert (workspace / "markers" / "marker_a.json").is_file()
    assert store.verify_event_log(workspace / store.EVENT_LOG_NAME)["valid"] is True


def test_ingest_sheet_is_idempotent(tmp_path, workspace, registry, sheet_factory):
    source = tmp_path / "submission.json"
    source.write_text(json.dumps(sheet_factory(registry, "marker_a", "MARKER_A_01")),
                      encoding="utf-8")
    first = sheets.ingest_sheet(workspace, "marker_a", source, registry)
    second = sheets.ingest_sheet(workspace, "marker_a", source, registry)
    assert first["changed"] is True
    assert second["changed"] is False
    assert len(list((workspace / "markers" / "original").glob("marker_a.*.json"))) == 1


def test_ingest_sheet_refuses_different_resubmission(tmp_path, workspace, registry,
                                                    sheet_factory):
    first_source = tmp_path / "first.json"
    first_source.write_text(
        json.dumps(sheet_factory(registry, "marker_a", "MARKER_A_01")),
        encoding="utf-8")
    sheets.ingest_sheet(workspace, "marker_a", first_source, registry)

    second_source = tmp_path / "second.json"
    second_source.write_text(
        json.dumps(sheet_factory(registry, "marker_a", "MARKER_A_01",
                                 flips={("q1", "M1#0")})),
        encoding="utf-8")
    with pytest.raises(store.StoreError, match="refusing to overwrite"):
        sheets.ingest_sheet(workspace, "marker_a", second_source, registry)
    assert len(list((workspace / "markers" / "original").glob("marker_a.*.json"))) == 2
