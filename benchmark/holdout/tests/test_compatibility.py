"""Criterion-code compatibility: no silent dropping, conversion or lossy pairing."""

from __future__ import annotations

import pytest

from benchmark.holdout import compatibility, paper, scoring


def test_supported_codes_are_scoreable(registry):
    report = compatibility.report(registry)
    assert report["scoreable"] is True
    assert report["unsupported_codes"] == []
    assert report["lossy_codes"] == []
    assert report["criteria_total"] == 50
    assert sum(entry["count"] for entry in report["codes"]) == 50


def test_dependency_alias_is_approved(registry_factory):
    registry = registry_factory(25, codes=("M1dep", "A1"))
    report = compatibility.report(registry)
    assert report["scoreable"] is True
    assert any(entry["code"] == "M1dep" and entry["kind"] == "dependency"
               for entry in report["codes"])


def test_unsupported_code_blocks(registry_factory):
    registry = registry_factory(25, codes=("C1", "A1"))
    report = compatibility.report(registry)
    assert report["scoreable"] is False
    assert report["unsupported_codes"] == ["C1"]
    with pytest.raises(compatibility.CompatibilityError, match="C1"):
        compatibility.assert_scoreable(report)


def test_lossy_mapping_is_rejected(registry_factory):
    registry = registry_factory(25, codes=("M1", "M1x"))
    report = compatibility.report(registry)
    assert report["scoreable"] is False
    assert report["lossy_codes"] == ["M1x"]
    assert report["collisions"]
    assert report["collisions"][0]["item"] == "q1"
    assert report["collisions"][0]["codes"] == ["M1", "M1x"]


def test_report_is_deterministic(registry):
    first = compatibility.report(registry)
    second = compatibility.report(registry)
    assert first["report_sha256"] == second["report_sha256"]


def test_scoring_refuses_unsupported_paper(registry_factory):
    registry = registry_factory(25, codes=("C1", "A1"))
    report = compatibility.report(registry)
    with pytest.raises(compatibility.CompatibilityError, match="C1"):
        scoring.evaluate({"paper_id": "holdout-01", "scoreable": False,
                          "compatibility": report}, {"items": []})


def test_legacy_paper01_is_scoreable():
    record = paper.load_paper("paper-01")
    assert record["scoreable"] is True
    assert record["compatibility"]["unsupported_codes"] == []
    assert record["compatibility"]["criteria_total"] == 87
