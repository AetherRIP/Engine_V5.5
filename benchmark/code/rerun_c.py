"""Run a fresh Strategy C attempt without touching A/B or prior C raw runs.

The normal benchmark driver intentionally rewrites a complete result set.  This
module is the opposite: it is scoped to C, loads the historical key counters
from ``key_pool_state.json``, appends new ledger rows, and writes only new
``c_run<N>.json`` files.  A rerun is only promoted to the current C result if
both runs are complete, the scheme extraction succeeded, at least one SymPy
check is ``different``, and every ``different`` check has an escalation.

Usage:
    python -m benchmark.code.rerun_c
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config, loader, regenerate
from .execution import Executor, ModelSelection, select_models
from .keypool import KeyPool
from .provider import GeminiClient
from .strategies import StrategyRunner
from .usage import UsageLedger


def next_run_id(raw_dir: Path | None = None) -> int:
    """Return the next unused numeric C run id; never reuse an old id."""
    raw_dir = raw_dir or (config.RESULTS_DIR / "raw")
    ids = []
    if raw_dir.is_dir():
        for path in raw_dir.glob("c_run*.json"):
            match = re.fullmatch(r"c_run(\d+)\.json", path.name)
            if match:
                ids.append(int(match.group(1)))
    return max(ids, default=0) + 1


def _attempt_diagnostics(payload: dict) -> dict:
    checks = payload.get("verification") or {}
    different_ids = {str(item_id) for item_id, check in checks.items()
                     if isinstance(check, dict) and check.get("status") == "different"}
    different = len(different_ids)
    escalations = {str(item_id) for item_id in (payload.get("escalations") or [])}
    changed = len(payload.get("escalation_changes") or [])
    gap = bool(different_ids - escalations)
    complete = (payload.get("completion_status") == "complete"
                and len(payload.get("items") or []) == len(loader.item_ids()))
    scheme_ok = not any("scheme extraction failed" in str(error)
                        for error in (payload.get("errors") or []))
    return {"different_checks": different, "escalation_count": len(escalations),
            "changed_marks": changed, "escalation_gap": gap, "complete": complete,
            "scheme_ok": scheme_ok,
            "valid": complete and scheme_ok and not gap and different > 0}


def main() -> int:
    parser = argparse.ArgumentParser(description="Append-only Strategy C rerun")
    parser.add_argument("--primary", help="verified primary model override")
    parser.add_argument("--lite", help="Lite marking model override")
    parser.add_argument("--strong", help="escalation model override")
    args = parser.parse_args()
    config.ensure_dirs()
    raw_dir = config.RESULTS_DIR / "raw"
    old_path = raw_dir / "c_run1.json"
    if not old_path.is_file():
        print(f"no historical C run at {old_path}; refusing to create a baseline", flush=True)
        return 2
    old = json.loads(old_path.read_text(encoding="utf-8"))
    models_data = old.get("models") or {}
    if not models_data.get("primary") or not models_data.get("lite"):
        print("historical C run has no usable model selection", flush=True)
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
              f"{key.network_state}/probe={key.probe_state}/pool={key.pool}", flush=True)
    if not eligible:
        print("no eligible key; a valid C rerun is impossible", flush=True)
        return 4

    client = GeminiClient()
    ledger = UsageLedger()
    selected = select_models(
        client, pool, ledger,
        primary_candidates=[args.primary] if args.primary else None)
    notes = list(models_data.get("notes") or []) + list(selected.notes)
    if args.primary:
        notes.append(
            f"primary override: {args.primary} used because the historical "
            f"{models_data['primary']} full-document requests returned HTTP 503")
    models = ModelSelection(
        primary=selected.primary,
        lite=args.lite or selected.lite or models_data["lite"],
        strong=args.strong or selected.strong or models_data.get("strong") or selected.primary,
        notes=notes,
    )
    verified_primary = any(
        note.startswith(f"primary: {selected.primary} verified on ")
        for note in selected.notes)
    if not verified_primary:
        print("no verified primary model; refusing to spend C requests", flush=True)
        return 6
    runner = StrategyRunner(Executor(client, pool, ledger), models)
    start = next_run_id(raw_dir)
    used_run_ids = []
    for row in ledger.rows():
        if row.get("strategy") == "c" and row.get("purpose") != "probe":
            try:
                used_run_ids.append(int(row.get("run")))
            except (TypeError, ValueError):
                pass
    start = max(start, max(used_run_ids, default=0) + 1)
    attempt_id = "c-rerun-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"models: primary={models.primary} lite={models.lite} strong={models.strong}", flush=True)
    print(f"attempt {attempt_id}; new run ids {start}, {start + 1}", flush=True)

    payloads: list[dict] = []
    diagnostics: list[dict] = []
    for offset in range(2):
        run_id = start + offset
        print(f"running C run {run_id}...", flush=True)
        started = time.monotonic()
        payload = runner.run_c(run_id).as_dict()
        payload["attempt_id"] = attempt_id
        payload["attempt_status"] = "pending"
        payload["rerun_of"] = "c"
        raw_path = raw_dir / f"c_run{run_id}.json"
        raw_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        diagnostic = _attempt_diagnostics(payload)
        diagnostics.append(diagnostic)
        payloads.append(payload)
        print(f"  requests={payload.get('request_count')} items={len(payload.get('items') or [])} "
              f"different={diagnostic['different_checks']} escalations={diagnostic['escalation_count']} "
              f"changed={diagnostic['changed_marks']} gap={diagnostic['escalation_gap']} "
              f"valid={diagnostic['valid']} elapsed={time.monotonic() - started:.1f}s", flush=True)

    all_valid = all(item["valid"] for item in diagnostics)
    live_changed = any(item["changed_marks"] > 0 for item in diagnostics)
    if all_valid and not live_changed:
        print("rerun not promoted: no live escalation changed an item's marks", flush=True)
    all_valid = all_valid and live_changed
    for payload in payloads:
        payload["attempt_status"] = "valid" if all_valid else "invalid"
        raw_path = raw_dir / f"c_run{payload['run']}.json"
        raw_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if not all_valid:
        print("rerun not promoted: both C runs must be complete with no escalation gap", flush=True)
        return 5

    historical = config.RESULTS_DIR / "strategy_c_historical.json"
    current = config.RESULTS_DIR / "strategy_c.json"
    if current.is_file() and not historical.is_file():
        shutil.copy2(current, historical)
    regenerate.main()
    print(f"promoted {attempt_id}; A/B raw and derived files were not touched", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
