"""Run a fresh Strategy A attempt without touching B, C or prior A raw runs.

The benchmark driver intentionally rewrites a complete result set.  This module
is scoped to A: it loads the historical key counters, appends new ledger rows,
and writes only the next ``a_run<N>.json``.  A rerun is promoted only when it
covers every scoreable item, either in the first whole-paper response or through
the documented output split.

Usage:
    python -m benchmark.code.rerun_a
"""

from __future__ import annotations

import json
import re
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
    """Return the next unused numeric A run id; never reuse an old id."""
    raw_dir = raw_dir or (config.RESULTS_DIR / "raw")
    ids = []
    if raw_dir.is_dir():
        for path in raw_dir.glob("a_run*.json"):
            match = re.fullmatch(r"a_run(\d+)\.json", path.name)
            if match:
                ids.append(int(match.group(1)))
    return max(ids, default=0) + 1


def _completion_diagnostics(payload: dict) -> dict:
    ids = set(loader.item_ids())
    returned = {str(item.get("id")) for item in (payload.get("items") or [])
                if isinstance(item, dict)}
    status = str(payload.get("completion_status") or "")
    complete = (status in {"complete", "complete_after_split"}
                and returned == ids
                and payload.get("invalid_responses", 0) == 0)
    split_runs = list(payload.get("splits") or [])
    return {
        "complete": complete,
        "items_returned": len(returned),
        "items_expected": len(ids),
        "missing": sorted(ids - returned),
        "completion_status": status,
        "split_requests": len(split_runs),
        "splits": split_runs,
    }


def main() -> int:
    config.ensure_dirs()
    raw_dir = config.RESULTS_DIR / "raw"
    old_path = raw_dir / "a_run2.json"
    if not old_path.is_file():
        old_path = raw_dir / "a_run1.json"
    if not old_path.is_file():
        print("no historical A run to copy the model configuration from", flush=True)
        return 2
    old = json.loads(old_path.read_text(encoding="utf-8"))
    models_data = old.get("models") or {}
    if not models_data.get("primary"):
        print("historical A run has no usable model selection", flush=True)
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
        print("no eligible key; a complete A rerun is impossible", flush=True)
        return 4

    models = ModelSelection(
        primary=models_data["primary"],
        lite=models_data.get("lite"),
        strong=models_data.get("strong") or models_data["primary"],
        notes=list(models_data.get("notes") or []),
    )
    client = GeminiClient()
    ledger = UsageLedger()
    runner = StrategyRunner(Executor(client, pool, ledger), models)
    run_id = next_run_id(raw_dir)
    attempt_id = "a-rerun-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"attempt {attempt_id}; new run id {run_id}", flush=True)

    started = time.monotonic()
    payload = runner.run_a(run_id).as_dict()
    payload["attempt_id"] = attempt_id
    payload["rerun_of"] = "a"
    diagnostic = _completion_diagnostics(payload)
    payload["attempt_status"] = "valid" if diagnostic["complete"] else "invalid"
    payload["attempt_status_reason"] = (
        "complete with all scoreable items"
        if diagnostic["complete"] else
        f"{diagnostic['completion_status']}; missing {', '.join(diagnostic['missing'])}"
    )
    raw_path = raw_dir / f"a_run{run_id}.json"
    raw_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(
        f"  requests={payload.get('request_count')} "
        f"items={diagnostic['items_returned']}/{diagnostic['items_expected']} "
        f"status={diagnostic['completion_status']} "
        f"splits={diagnostic['split_requests']} "
        f"valid={diagnostic['complete']} "
        f"elapsed={time.monotonic() - started:.1f}s",
        flush=True,
    )
    for split in diagnostic["splits"]:
        print(
            f"  split {split.get('request')}: requested={split.get('requested_ids')} "
            f"returned={split.get('returned_ids')} status={split.get('status')} "
            f"finish={split.get('finish_reason')}",
            flush=True,
        )
    if diagnostic["missing"]:
        print(f"  missing: {', '.join(diagnostic['missing'])}", flush=True)
    print(f"  raw: {raw_path}", flush=True)

    if not diagnostic["complete"]:
        print("A rerun not promoted: all 38 scoreable items were not returned", flush=True)
        return 5

    regenerate.main()
    print(f"promoted {attempt_id}; B/C raw and derived files were not touched", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
