"""Run a fresh Strategy B pair without touching A/C or prior B raw runs.

The current B extractor re-reads a page once when its first transcription leaves
an item empty.  This module records two new append-only B runs, promotes them
only when both cover all 38 scoreable items, and regenerates the derived
artifacts from the preserved ledger.

Usage:
    python -m benchmark.code.rerun_b
"""

from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config, loader, regenerate
from .execution import Executor, ModelSelection
from .keypool import KeyPool
from .provider import GeminiClient
from .strategies import StrategyRunner
from .usage import UsageLedger


def next_run_id(raw_dir: Path | None = None) -> int:
    """Return the next unused numeric B run id; never reuse an old id."""
    raw_dir = raw_dir or (config.RESULTS_DIR / "raw")
    ids = []
    if raw_dir.is_dir():
        for path in raw_dir.glob("b_run*.json"):
            match = re.fullmatch(r"b_run(\d+)\.json", path.name)
            if match:
                ids.append(int(match.group(1)))
    return max(ids, default=0) + 1


def _diagnostics(payload: dict) -> dict:
    ids = set(loader.item_ids())
    returned = {str(item.get("id")) for item in (payload.get("items") or [])
                if isinstance(item, dict)}
    extraction = payload.get("extractions") or {}
    return {
        "complete": (payload.get("completion_status") == "complete"
                     and returned == ids),
        "items_returned": len(returned),
        "items_expected": len(ids),
        "missing": sorted(ids - returned),
        "retried_ids": extraction.get("retried_ids") or [],
        "retry_requests": extraction.get("retry_requests") or 0,
        "empty_after_retry": extraction.get("empty_after_retry") or [],
        "completion_status": payload.get("completion_status"),
    }


def main() -> int:
    config.ensure_dirs()
    raw_dir = config.RESULTS_DIR / "raw"
    old_path = raw_dir / "b_run1.json"
    if not old_path.is_file():
        print(f"no historical B run at {old_path}; refusing to create a baseline", flush=True)
        return 2
    old = json.loads(old_path.read_text(encoding="utf-8"))
    models_data = old.get("models") or {}
    if not models_data.get("primary"):
        print("historical B run has no usable model selection", flush=True)
        return 2

    secrets = config.read_api_keys()
    if not secrets:
        print("no API keys available", flush=True)
        return 3
    pool = KeyPool.from_state(secrets)
    eligible = [key for key in pool.keys if key.available()]
    print(f"historical key counters loaded; usable keys: {len(eligible)}", flush=True)
    for key in pool.keys:
        print(f"  {key.label}: {key.key_validity}/{key.quota_state}/"
              f"{key.network_state}/probe={key.probe_state}/pool={key.pool}",
              flush=True)
    if not eligible:
        print("no eligible key; a valid B rerun is impossible", flush=True)
        return 4

    models = ModelSelection(
        primary=models_data["primary"], lite=models_data.get("lite"),
        strong=models_data.get("strong") or models_data["primary"],
        notes=list(models_data.get("notes") or []),
    )
    client = GeminiClient()
    ledger = UsageLedger()
    runner = StrategyRunner(Executor(client, pool, ledger), models)
    start = next_run_id(raw_dir)
    attempt_id = "b-rerun-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"attempt {attempt_id}; new run ids {start}, {start + 1}", flush=True)

    payloads: list[dict] = []
    diagnostics: list[dict] = []
    for offset in range(2):
        run_id = start + offset
        print(f"running B run {run_id}...", flush=True)
        started = time.monotonic()
        payload = runner.run_b(run_id).as_dict()
        payload["attempt_id"] = attempt_id
        payload["rerun_of"] = "b"
        raw_path = raw_dir / f"b_run{run_id}.json"
        raw_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        diagnostic = _diagnostics(payload)
        diagnostics.append(diagnostic)
        payloads.append(payload)
        print(
            f"  requests={payload.get('request_count')} items={diagnostic['items_returned']}/"
            f"{diagnostic['items_expected']} retries={diagnostic['retry_requests']} "
            f"empty={diagnostic['empty_after_retry']} valid={diagnostic['complete']} "
            f"elapsed={time.monotonic() - started:.1f}s",
            flush=True,
        )

    all_valid = all(item["complete"] for item in diagnostics)
    for payload in payloads:
        payload["attempt_status"] = "valid" if all_valid else "invalid"
        raw_path = raw_dir / f"b_run{payload['run']}.json"
        raw_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if not all_valid:
        print("B rerun not promoted: both runs must cover all 38 scoreable items", flush=True)
        return 5

    historical = config.RESULTS_DIR / "strategy_b_historical.json"
    current = config.RESULTS_DIR / "strategy_b.json"
    if current.is_file() and not historical.is_file():
        shutil.copy2(current, historical)
    regenerate.main()
    print(f"promoted {attempt_id}; A/C raw and derived files were not touched", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
