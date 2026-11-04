"""Paper-scoped loading: two papers, mixing rejection and paper-01 regression."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.code import evaluator
from benchmark.holdout import paper, scoring, store


def _load(workspace, registry):
    return paper.load_workspace(workspace, paper_id=registry["paper_id"],
                                root=store.BENCHMARK_DIR,
                                code_root=store.BENCHMARK_DIR)


def test_loads_a_certified_holdout_paper(tmp_path, registry, sheet_factory,
                                        adjudication_factory, certified_paper):
    workspace = tmp_path / "holdout-01"
    certified_paper(workspace, registry,
                    sheet_factory(registry, "marker_a", "MARKER_A_01"),
                    sheet_factory(registry, "marker_b", "MARKER_B_01"),
                    adjudication_factory(registry, []))
    record = _load(workspace, registry)
    assert record["source"] == "holdout"
    assert record["scoreable"] is True
    assert len(record["items"]) == 25
    assert record["totals"]["candidate_marks_awarded"] == 50
    assert record["pages"]["student"] and record["pages"]["scheme"]
    assert record["certification_status"] == "attested_pending_approval"


def test_loads_a_second_independent_paper(tmp_path, registry_factory, sheet_factory,
                                         adjudication_factory, certified_paper):
    registry = registry_factory(25, paper_id="holdout-02")
    workspace = tmp_path / "holdout-02"
    certified_paper(workspace, registry,
                    sheet_factory(registry, "marker_a", "MARKER_A_02"),
                    sheet_factory(registry, "marker_b", "MARKER_B_02"),
                    adjudication_factory(registry, []))
    record = paper.load_paper("holdout-02", root=store.BENCHMARK_DIR,
                              papers_dir=tmp_path, code_root=store.BENCHMARK_DIR)
    assert record["paper_id"] == "holdout-02"
    assert record["reference"]["paper_id"] == "holdout-02"
    assert len(record["items"]) == 25


def test_rejects_cross_paper_artifact_mixing(tmp_path, registry, sheet_factory,
                                             adjudication_factory, certified_paper):
    workspace = tmp_path / "holdout-01"
    certified_paper(workspace, registry,
                    sheet_factory(registry, "marker_a", "MARKER_A_01"),
                    sheet_factory(registry, "marker_b", "MARKER_B_01"),
                    adjudication_factory(registry, []))
    path = workspace / "reference.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["paper_id"] = "holdout-99"
    store.write_json_atomic(path, data, replace=True)
    with pytest.raises(paper.PaperError, match="paper_id"):
        _load(workspace, registry)


def test_rejects_missing_reference(tmp_path, registry, sheet_factory,
                                   adjudication_factory, certified_paper):
    workspace = tmp_path / "holdout-01"
    certified_paper(workspace, registry,
                    sheet_factory(registry, "marker_a", "MARKER_A_01"),
                    sheet_factory(registry, "marker_b", "MARKER_B_01"),
                    adjudication_factory(registry, []))
    (workspace / "reference.json").unlink()
    with pytest.raises(paper.PaperError, match="reference.json"):
        _load(workspace, registry)


def test_rejects_modified_reference(tmp_path, registry, sheet_factory,
                                    adjudication_factory, certified_paper):
    workspace = tmp_path / "holdout-01"
    certified_paper(workspace, registry,
                    sheet_factory(registry, "marker_a", "MARKER_A_01"),
                    sheet_factory(registry, "marker_b", "MARKER_B_01"),
                    adjudication_factory(registry, []))
    path = workspace / "reference.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["totals"]["candidate_marks_awarded"] -= 1
    store.write_json_atomic(path, data, replace=True)
    with pytest.raises(paper.PaperError):
        _load(workspace, registry)


def test_rejects_unknown_paper_id(tmp_path):
    with pytest.raises(paper.PaperError):
        paper.load_paper("holdout-99", papers_dir=tmp_path)


def test_rejects_duplicate_item_ids(tmp_path, registry, sheet_factory,
                                    adjudication_factory, certified_paper):
    workspace = tmp_path / "holdout-01"
    certified_paper(workspace, registry,
                    sheet_factory(registry, "marker_a", "MARKER_A_01"),
                    sheet_factory(registry, "marker_b", "MARKER_B_01"),
                    adjudication_factory(registry, []))
    path = workspace / "items.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["items"][1]["id"] = data["items"][0]["id"]
    store.write_json_atomic(path, data, replace=True)
    with pytest.raises(paper.PaperError, match="duplicate item id"):
        _load(workspace, registry)


def test_rejects_inconsistent_totals(tmp_path, registry, sheet_factory,
                                     adjudication_factory, certified_paper):
    workspace = tmp_path / "holdout-01"
    certified_paper(workspace, registry,
                    sheet_factory(registry, "marker_a", "MARKER_A_01"),
                    sheet_factory(registry, "marker_b", "MARKER_B_01"),
                    adjudication_factory(registry, []))
    path = workspace / "reference.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["totals"]["marks_available_scored"] += 1
    store.write_json_atomic(path, data, replace=True)
    with pytest.raises(paper.PaperError):
        _load(workspace, registry)


def test_rejects_missing_criterion_records(tmp_path, registry, sheet_factory,
                                           adjudication_factory, certified_paper):
    workspace = tmp_path / "holdout-01"
    certified_paper(workspace, registry,
                    sheet_factory(registry, "marker_a", "MARKER_A_01"),
                    sheet_factory(registry, "marker_b", "MARKER_B_01"),
                    adjudication_factory(registry, []))
    path = workspace / "reference.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["items"][0]["criteria"].pop()
    store.write_json_atomic(path, data, replace=True)
    with pytest.raises(paper.PaperError):
        _load(workspace, registry)


def test_legacy_paper01_loads_explicitly():
    record = paper.load_paper("paper-01")
    assert record["source"] == "legacy_candidate"
    assert record["holdout_eligible"] is False
    assert record["totals"]["marks_available_scored"] == 87
    assert record["totals"]["candidate_marks_awarded"] == 80
    assert len(record["items"]) == 38


def test_paper01_results_are_unchanged():
    runs = json.loads((store.BENCHMARK_DIR / "experimental" / "results" /
                       "h_runs.json").read_text(encoding="utf-8"))
    run = runs["h-low"][0]
    record = paper.load_paper("paper-01")
    baseline = evaluator.evaluate_run(run)
    explicit = evaluator.evaluate_run(run, reference=record["reference"])
    assert baseline == explicit
    scoped = scoring.evaluate(record, run)
    for key, value in baseline.items():
        assert scoped[key] == value
    assert scoped["paper_id"] == "paper-01"
