"""Safe, immutable evidence storage for holdout paper intake.

This module knows nothing about marking.  It creates a paper workspace, copies evidence
without silently overwriting it, hashes it, and can prove later that it has not changed.

Every write is atomic (temp file in the destination directory, ``os.replace``) so an
interrupted intake cannot leave a half-written artefact behind.  Replacing existing
evidence is opt-in and archives the previous bytes instead of destroying them.

The event log is an append-only hash chain: each row commits to the previous row's hash,
so editing an old row is detectable even without external storage.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import manifest

HOLDOUT_DIR = Path(__file__).resolve().parent
BENCHMARK_DIR = HOLDOUT_DIR.parent
PAPERS_DIR = HOLDOUT_DIR / "papers"
EVENT_LOG_NAME = "events.jsonl"
HISTORY_DIR_NAME = "history"
PAGE_ROLES = ("student", "scheme")
PAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
MAX_PAGE_BYTES = 20 * 1024 * 1024
ZERO_HASH = "0" * 64
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class StoreError(RuntimeError):
    """A storage rule was violated.  Nothing is written when this is raised."""


# --------------------------------------------------------------------------- hashing
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ------------------------------------------------------------------------- workspace
def validate_paper_id(paper_id: object) -> str:
    """Accept ``holdout-NN`` only; never the reserved design paper."""
    value = str(paper_id or "").strip()
    if value in manifest.RESERVED_PAPER_IDS:
        raise StoreError(f"paper_id {value!r} is reserved for the design paper")
    if not manifest.PAPER_ID_PATTERN.match(value):
        raise StoreError(f"paper_id {value!r} is not of the form holdout-NN")
    return value


def safe_child(root: Path, *parts: str) -> Path:
    """Join ``parts`` under ``root``, rejecting traversal and escaping symlinks."""
    root = Path(root)
    for part in parts:
        text = str(part)
        if not text or text in {".", ".."} or "/" in text or "\\" in text:
            raise StoreError(f"unsafe path component {text!r}")
        if Path(text).is_absolute():
            raise StoreError(f"unsafe absolute path component {text!r}")
    target = root.joinpath(*[str(part) for part in parts])
    resolved_root = root.resolve(strict=False)
    resolved_target = target.resolve(strict=False)
    if resolved_target != resolved_root and resolved_root not in resolved_target.parents:
        raise StoreError(f"{target} escapes {root}")
    return target


def ensure_workspace(paper_id: object, *, papers_dir: Path | None = None) -> Path:
    """Create (or reuse) the paper workspace and its fixed sub-directories."""
    root = Path(papers_dir) if papers_dir is not None else PAPERS_DIR
    root.mkdir(parents=True, exist_ok=True)
    workspace = safe_child(root, validate_paper_id(paper_id))
    if workspace.exists():
        if workspace.is_symlink() or not workspace.is_dir():
            raise StoreError(f"{workspace} exists and is not a plain directory")
    else:
        workspace.mkdir()
    for relative in (("pages", "student"), ("pages", "scheme"), ("markers",),
                     ("attestations",), (HISTORY_DIR_NAME,)):
        safe_child(workspace, *relative).mkdir(parents=True, exist_ok=True)
    return workspace


# ---------------------------------------------------------------------- atomic write
def _archive(path: Path) -> dict:
    """Move an existing file into its ``history`` directory, preserving the bytes."""
    history = path.parent / HISTORY_DIR_NAME
    history.mkdir(parents=True, exist_ok=True)
    digest = sha256_file(path)
    candidate = history / f"{path.stem}.{digest[:12]}{path.suffix}"
    counter = 1
    while candidate.exists():
        candidate = history / f"{path.stem}.{digest[:12]}.{counter}{path.suffix}"
        counter += 1
    os.replace(path, candidate)
    return {"archived_to": str(candidate.name), "sha256": digest}


def write_bytes_atomic(path: Path, data: bytes, *, replace: bool = False) -> dict:
    """Write bytes atomically; identical content is a no-op, different content refuses."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = sha256_bytes(data)
    if path.exists():
        if path.is_dir():
            raise StoreError(f"{path} is a directory")
        existing = sha256_file(path)
        if existing == digest:
            return {"path": str(path), "sha256": digest, "bytes": len(data),
                    "changed": False}
        if not replace:
            raise StoreError(
                f"refusing to overwrite {path.name}: existing sha256 {existing[:12]}… "
                "differs; pass replace=True to archive it first")
        _archive(path)

    fd, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-",
                                     suffix=path.suffix or ".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = ""
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return {"path": str(path), "sha256": digest, "bytes": len(data), "changed": True}


def write_json_atomic(path: Path, payload: object, *, replace: bool = False) -> dict:
    data = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n").encode("utf-8")
    return write_bytes_atomic(path, data, replace=replace)


def read_json_value(path: Path):
    """Read any JSON value (audit evidence is a list, most artifacts are objects)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise StoreError(f"{path}: cannot read JSON ({error})") from error


def read_json(path: Path) -> dict:
    value = read_json_value(path)
    if not isinstance(value, dict):
        raise StoreError(f"{path}: JSON root is not an object")
    return value


# --------------------------------------------------------------------------- records
def file_record(path: Path, *, root: Path | None = None) -> dict:
    """Hash a file and record a path relative to ``root`` (the workspace by default)."""
    path = Path(path)
    base = Path(root) if root is not None else path.parent
    try:
        relative = path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        relative = path.name
    return {"path": relative, "name": path.name, "sha256": sha256_file(path),
            "bytes": path.stat().st_size}


def _page_name(name: str) -> str:
    cleaned = _UNSAFE_NAME.sub("_", Path(name).name).strip("._")
    if not cleaned:
        raise StoreError(f"page name {name!r} is empty after sanitisation")
    if Path(cleaned).suffix.lower() not in PAGE_SUFFIXES:
        raise StoreError(f"page {name!r} is not a PNG or JPEG image")
    return cleaned


def add_pages(workspace: Path, role: str, sources: list[Path], *,
              reserved_hashes: set[str] | None = None,
              replace: bool = False) -> list[dict]:
    """Copy pages into ``pages/<role>/`` with duplicate and reserved-hash checks."""
    if role not in PAGE_ROLES:
        raise StoreError(f"unknown page role {role!r}")
    workspace = Path(workspace)
    reserved = (manifest.reserved_page_hashes() if reserved_hashes is None
                else set(reserved_hashes))
    destination = safe_child(workspace, "pages", role)
    destination.mkdir(parents=True, exist_ok=True)

    existing: dict[str, str] = {}
    for path in sorted(destination.iterdir()):
        if path.is_file() and not path.is_symlink():
            existing.setdefault(sha256_file(path), path.name)

    records: list[dict] = []
    seen: dict[str, str] = {}
    for source in sources:
        path = Path(source)
        if path.is_symlink() or not path.is_file():
            raise StoreError(f"{path}: source page is missing or is a symlink")
        name = _page_name(path.name)
        size = path.stat().st_size
        if size <= 0:
            raise StoreError(f"{name}: page is empty")
        if size > MAX_PAGE_BYTES:
            raise StoreError(f"{name}: page is larger than {MAX_PAGE_BYTES} bytes")
        digest = sha256_file(path)
        if digest in reserved:
            raise StoreError(f"{name}: page hash matches a reserved paper-01 page")
        if digest in seen:
            raise StoreError(f"{name}: duplicate page content (also {seen[digest]})")
        if digest in existing and existing[digest] != name:
            raise StoreError(
                f"{name}: duplicate page content already stored as {existing[digest]}")
        seen[digest] = name
        target = safe_child(destination, name)
        result = write_bytes_atomic(target, path.read_bytes(), replace=replace)
        existing[digest] = name
        records.append({
            **file_record(target, root=workspace),
            "role": role,
            "source_name": path.name,
            "changed": result["changed"],
        })
    return records


# --------------------------------------------------------------------- verification
def check_duplicate_hashes(records: list[dict]) -> list[str]:
    by_hash: dict[str, list[str]] = {}
    for record in records:
        by_hash.setdefault(str(record.get("sha256")), []).append(str(record.get("name")))
    return [f"duplicate content: {', '.join(names)}"
            for names in by_hash.values() if len(names) > 1]


def verify_artifact(path: Path, expected_sha256: str) -> list[str]:
    path = Path(path)
    if not path.is_file():
        return [f"{path.name}: file is missing"]
    actual = sha256_file(path)
    if actual != expected_sha256:
        return [f"{path.name}: hash mismatch (expected {str(expected_sha256)[:12]}…, "
                f"found {actual[:12]}…)"]
    return []


def verify_evidence(workspace: Path, expected: dict[str, str]) -> dict:
    """Re-hash stored evidence against a recorded {relative_path: sha256} map."""
    problems: list[str] = []
    for relative, digest in sorted(expected.items()):
        try:
            path = safe_child(Path(workspace), *Path(relative).parts)
        except StoreError as error:
            problems.append(str(error))
            continue
        problems.extend(verify_artifact(path, digest))
    return {"valid": not problems, "checked": len(expected), "problems": problems}


def verify_frozen_digests(frozen_config: dict, *, code_root: Path | None = None) -> list[str]:
    """Check the pre-registered Strategy H/scoring files have not changed.

    Registration must call this before it writes a manifest revision.
    """
    root = Path(code_root) if code_root is not None else BENCHMARK_DIR
    files = (frozen_config or {}).get("files") or {}
    problems: list[str] = []
    if not files:
        problems.append("frozen_config has no file digests")
    for relative, expected in sorted(files.items()):
        path = root / relative
        if not path.is_file():
            problems.append(f"frozen file missing: {relative}")
        elif sha256_file(path) != expected:
            problems.append(f"frozen file changed since pre-registration: {relative}")
    return problems


def assert_frozen_digests(frozen_config: dict, *, code_root: Path | None = None) -> None:
    problems = verify_frozen_digests(frozen_config, code_root=code_root)
    if problems:
        raise StoreError("; ".join(problems))


# ------------------------------------------------------------------------- event log
def _canonical(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _read_event_rows(path: Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    rows: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as error:
            raise StoreError(f"{path}: malformed event row {number}") from error
        if not isinstance(row, dict):
            raise StoreError(f"{path}: event row {number} is not an object")
        rows.append(row)
    return rows


def append_event(workspace: Path, event: str, **fields) -> dict:
    """Append one hash-chained row; the chain makes silent edits detectable."""
    path = Path(workspace) / EVENT_LOG_NAME
    rows = _read_event_rows(path)
    previous = rows[-1].get("hash") if rows else ZERO_HASH
    row = {"seq": len(rows) + 1, "at": now_iso(), "event": str(event),
           "fields": fields, "prev": previous}
    row["hash"] = sha256_bytes(_canonical(row))
    try:
        with path.open("ab") as handle:
            handle.write((json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
                         .encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise StoreError(f"{path}: cannot append event ({error})") from error
    return row


def verify_event_log(path: Path) -> dict:
    problems: list[str] = []
    previous = ZERO_HASH
    try:
        rows = _read_event_rows(path)
    except StoreError as error:
        return {"valid": False, "rows": 0, "problems": [str(error)]}
    for index, row in enumerate(rows, start=1):
        if row.get("seq") != index:
            problems.append(f"row {index}: sequence is {row.get('seq')!r}")
        if row.get("prev") != previous:
            problems.append(f"row {index}: previous hash does not match")
        digest = row.get("hash")
        copy = {key: value for key, value in row.items() if key != "hash"}
        if sha256_bytes(_canonical(copy)) != digest:
            problems.append(f"row {index}: hash does not match its contents")
        previous = digest
    return {"valid": not problems, "rows": len(rows), "problems": problems}
