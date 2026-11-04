"""Storage tests: hashing, immutability, atomic writes and tamper detection."""

from __future__ import annotations

import json

import pytest

from benchmark.holdout import manifest, store


def _write(tmp_path, name, data):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_paper_id_validation():
    assert store.validate_paper_id("holdout-01") == "holdout-01"
    for bad in ("paper-01", "holdout-1", "../holdout-01", "holdout-01/x", "",
                "HOLDOUT-01"):
        with pytest.raises(store.StoreError):
            store.validate_paper_id(bad)


def test_workspace_creation_is_idempotent(tmp_path):
    first = store.ensure_workspace("holdout-02", papers_dir=tmp_path / "papers")
    second = store.ensure_workspace("holdout-02", papers_dir=tmp_path / "papers")
    assert first == second
    assert (first / "pages" / "student").is_dir()
    assert (first / "pages" / "scheme").is_dir()
    assert (first / "markers").is_dir()
    assert (first / "attestations").is_dir()


def test_workspace_rejects_file_at_path(tmp_path):
    root = tmp_path / "papers"
    root.mkdir()
    (root / "holdout-03").write_text("not a workspace")
    with pytest.raises(store.StoreError, match="not a plain directory"):
        store.ensure_workspace("holdout-03", papers_dir=root)


def test_safe_child_rejects_traversal_and_absolute(tmp_path):
    for bad in ("..", "a/b", "a\\b", str(tmp_path / "x")):
        with pytest.raises(store.StoreError):
            store.safe_child(tmp_path, bad)


def test_add_pages_copies_and_hashes(tmp_path, workspace):
    source = _write(tmp_path, "page.png", b"page-one")
    records = store.add_pages(workspace, "student", [source], reserved_hashes=set())
    assert records[0]["path"] == "pages/student/page.png"
    assert records[0]["sha256"] == store.sha256_bytes(b"page-one")
    assert (workspace / "pages" / "student" / "page.png").read_bytes() == b"page-one"


def test_add_pages_rejects_duplicate_content(tmp_path, workspace):
    first = _write(tmp_path, "a.png", b"same bytes")
    second = _write(tmp_path, "b.png", b"same bytes")
    with pytest.raises(store.StoreError, match="duplicate page content"):
        store.add_pages(workspace, "scheme", [first, second], reserved_hashes=set())


def test_add_pages_rejects_duplicate_already_stored(tmp_path, workspace):
    first = _write(tmp_path, "a.png", b"same bytes")
    store.add_pages(workspace, "student", [first], reserved_hashes=set())
    second = _write(tmp_path, "b.png", b"same bytes")
    with pytest.raises(store.StoreError, match="already stored as"):
        store.add_pages(workspace, "student", [second], reserved_hashes=set())


def test_add_pages_rejects_paper01_collision(tmp_path, workspace, monkeypatch):
    reserved = manifest.reserved_page_hashes()
    assert reserved, "paper-01 page hashes must still be available"
    monkeypatch.setattr(store, "sha256_file", lambda path: next(iter(reserved)))
    source = _write(tmp_path, "page.png", b"looks-new")
    with pytest.raises(store.StoreError, match="reserved paper-01"):
        store.add_pages(workspace, "student", [source], reserved_hashes=reserved)


def test_add_pages_refuses_silent_overwrite(tmp_path, workspace):
    source = _write(tmp_path, "one/page.png", b"first")
    store.add_pages(workspace, "student", [source], reserved_hashes=set())
    replacement = _write(tmp_path, "two/page.png", b"second")
    with pytest.raises(store.StoreError, match="refusing to overwrite"):
        store.add_pages(workspace, "student", [replacement], reserved_hashes=set())
    assert (workspace / "pages" / "student" / "page.png").read_bytes() == b"first"


def test_add_pages_replace_archives_previous(tmp_path, workspace):
    source = _write(tmp_path, "one/page.png", b"first")
    store.add_pages(workspace, "student", [source], reserved_hashes=set())
    replacement = _write(tmp_path, "two/page.png", b"second")
    store.add_pages(workspace, "student", [replacement], reserved_hashes=set(),
                    replace=True)
    assert (workspace / "pages" / "student" / "page.png").read_bytes() == b"second"
    archived = list((workspace / "pages" / "student" / "history").glob("page.*.png"))
    assert archived and archived[0].read_bytes() == b"first"


def test_add_pages_rejects_non_image_and_empty(tmp_path, workspace):
    text = _write(tmp_path, "notes.txt", b"x")
    with pytest.raises(store.StoreError, match="PNG or JPEG"):
        store.add_pages(workspace, "student", [text], reserved_hashes=set())
    empty = _write(tmp_path, "empty.png", b"")
    with pytest.raises(store.StoreError, match="empty"):
        store.add_pages(workspace, "student", [empty], reserved_hashes=set())


def test_add_pages_rejects_oversize(tmp_path, workspace, monkeypatch):
    monkeypatch.setattr(store, "MAX_PAGE_BYTES", 4)
    source = _write(tmp_path, "big.png", b"12345")
    with pytest.raises(store.StoreError, match="larger than"):
        store.add_pages(workspace, "student", [source], reserved_hashes=set())


def test_atomic_write_leaves_no_partial_file(tmp_path, monkeypatch):
    path = tmp_path / "certification.json"

    def boom(source, destination):
        raise OSError("disk full")

    monkeypatch.setattr(store.os, "replace", boom)
    with pytest.raises(OSError):
        store.write_json_atomic(path, {"paper_id": "holdout-01"})
    assert not path.exists()
    assert not list(tmp_path.glob(".tmp-*"))


def test_write_json_is_deterministic(tmp_path):
    path = tmp_path / "a.json"
    store.write_json_atomic(path, {"b": 1, "a": [2]})
    first = path.read_bytes()
    result = store.write_json_atomic(path, {"a": [2], "b": 1})
    assert path.read_bytes() == first
    assert result["changed"] is False


def test_verify_evidence_detects_tamper(tmp_path, workspace):
    path = workspace / "certification.json"
    store.write_json_atomic(path, {"paper_id": "holdout-01"})
    expected = {"certification.json": store.sha256_file(path)}
    assert store.verify_evidence(workspace, expected)["valid"] is True
    path.write_text('{"paper_id": "tampered"}\n', encoding="utf-8")
    result = store.verify_evidence(workspace, expected)
    assert result["valid"] is False
    assert any("hash mismatch" in problem for problem in result["problems"])


def test_verify_evidence_reports_missing_file(tmp_path, workspace):
    result = store.verify_evidence(workspace, {"missing.json": "0" * 64})
    assert result["valid"] is False
    assert any("missing" in problem for problem in result["problems"])


def test_event_log_chain_detects_edit(tmp_path, workspace):
    store.append_event(workspace, "workspace_created")
    store.append_event(workspace, "pages_added", role="student")
    log = workspace / store.EVENT_LOG_NAME
    assert store.verify_event_log(log)["valid"] is True
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    rows[0]["event"] = "rewritten"
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    result = store.verify_event_log(log)
    assert result["valid"] is False
    assert any("hash does not match" in problem for problem in result["problems"])


def test_event_log_chain_detects_reordering(tmp_path, workspace):
    store.append_event(workspace, "one")
    store.append_event(workspace, "two")
    log = workspace / store.EVENT_LOG_NAME
    lines = log.read_text(encoding="utf-8").splitlines()
    log.write_text("\n".join([lines[1], lines[0]]) + "\n", encoding="utf-8")
    assert store.verify_event_log(log)["valid"] is False


def test_frozen_digest_gate_detects_change(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    frozen = code / "signals.py"
    frozen.write_text("FROZEN = 1\n")
    config = {"files": {"signals.py": store.sha256_file(frozen)}}
    assert store.verify_frozen_digests(config, code_root=code) == []
    frozen.write_text("FROZEN = 2\n")
    problems = store.verify_frozen_digests(config, code_root=code)
    assert any("changed since pre-registration" in problem for problem in problems)
    with pytest.raises(store.StoreError):
        store.assert_frozen_digests(config, code_root=code)
