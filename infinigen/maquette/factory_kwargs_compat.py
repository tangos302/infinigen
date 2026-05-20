"""v5-3: shared helper for tolerating LLM-invented unknown factory kwargs.

LLM-authored build.py scripts occasionally pass kwargs that don't exist on
the target factory (`foliage_archetype_param=None if False else None` on
NativeLowPolyTreeFactory in the v4 sweep). The TypeError that results kills
a 5-minute build over a one-line typo.

This module provides `accept_unused_kwargs(factory_name, kwargs)` which:
1. Returns silently when there are no unknown kwargs.
2. Otherwise emits a single-line stderr warning so the audit trail shows
   what was swallowed — picked up by `blender_stderr.log` and any sweep
   diagnostic.
3. Appends a structured record to `<MAQUETTE_OUT_DIR>/factory_unused_kwargs.json`
   (best-effort; failures here never crash the build).

The factory's `__init__` does:

    def __init__(self, factory_seed, ..., real_arg=42, **_unused_kwargs):
        accept_unused_kwargs("LowPolyXxxFactory", _unused_kwargs)
        super().__init__(...)

Naming convention: kwargs that match a parameter's REAL name continue to
work; only unrecognised names land in `**_unused_kwargs` and get tolerated.
Serious constructor errors (wrong type for a known kwarg, missing required
positional arg) still surface normally — this helper only handles unknown
names.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping


def accept_unused_kwargs(
    factory_name: str,
    unused_kwargs: Mapping[str, Any],
) -> None:
    """Warn + record unknown kwargs. No-op when there are none."""
    if not unused_kwargs:
        return
    keys = sorted(unused_kwargs.keys())
    # 1. stderr line — single line, machine-greppable prefix.
    try:
        print(
            f"[factory_unused_kwargs] {factory_name}: ignoring "
            f"{keys}  (LLM-invented names; constructor used defaults).",
            file=sys.stderr,
        )
    except Exception:  # noqa: BLE001
        pass
    # 2. Append to sidecar JSON under MAQUETTE_OUT_DIR. Best-effort.
    out_dir_env = os.environ.get("MAQUETTE_OUT_DIR")
    if not out_dir_env:
        return
    out_path = Path(out_dir_env) / "factory_unused_kwargs.json"
    record = {
        "ts": time.time(),
        "factory": factory_name,
        "ignored_keys": keys,
        # Stringify values so non-serialisable types (mathutils.Vector, etc.)
        # don't break json.dump.
        "ignored_values": {k: repr(unused_kwargs[k]) for k in keys},
    }
    try:
        existing: list[dict[str, Any]] = []
        if out_path.is_file():
            try:
                payload = json.loads(out_path.read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    existing = payload
            except Exception:  # noqa: BLE001
                existing = []
        existing.append(record)
        out_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        # Audit failure is non-fatal — stderr trace already exists.
        pass
