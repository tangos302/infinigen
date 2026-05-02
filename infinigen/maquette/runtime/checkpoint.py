"""Phase-checkpoint helper for the maquette pipeline.

Build scripts call ``checkpoint('terrain')`` etc. at major build
boundaries. Each call:
  - exports the current scene to ``$RUN_DIR/map.obj`` (overwriting),
  - writes a phase-marker JSON to ``$RUN_DIR/_phase_{name}.json``,

The songe-core runner tails the run dir for new phase markers and
publishes them in ``maquette_live.json``. The frontend's 3D viewer
cache-busts the OBJ URL on phase changes, so the user sees the scene
evolve from terrain → foliage → buildings → final.

If ``MAQUETTE_OUT_DIR`` isn't set in the environment (e.g. someone runs
the build script outside the pipeline) the checkpoint becomes a no-op
so scripts don't crash standalone.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


_PHASE_HISTORY: list[str] = []


def _resolve_run_dir() -> Path | None:
    """``MAQUETTE_OUT_DIR`` points at ``maquette_session/`` inside the
    songe-core run dir. The run dir is one level up. Standalone runs
    that point straight at a custom directory still work — we write
    the marker + obj into that directory."""
    raw = os.environ.get("MAQUETTE_OUT_DIR")
    if not raw:
        return None
    out_dir = Path(raw)
    # Songe-core layout: out_dir.name == "maquette_session"; the run dir
    # is its parent. Standalone layout: out_dir IS the run dir.
    if out_dir.name == "maquette_session":
        return out_dir.parent
    return out_dir


def checkpoint(phase_name: str) -> str | None:
    """Export current scene as map.obj and write a phase marker.

    Returns the OBJ path on success, ``None`` if the env isn't set up
    (no-op for standalone runs).
    """
    run_dir = _resolve_run_dir()
    if run_dir is None:
        return None
    run_dir.mkdir(parents=True, exist_ok=True)

    import bpy

    # Make every mesh visible to render + select it for the export filter.
    for o in bpy.data.objects:
        if o.type == "MESH":
            o.hide_render = False
            o.hide_viewport = False
    bpy.ops.object.select_all(action="DESELECT")
    has_mesh = False
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        try:
            o.select_set(True)
            has_mesh = True
        except RuntimeError:
            # Object is in a collection not visible to the current
            # ViewLayer (e.g. Building Tools' internal helper objects);
            # safe to skip — it doesn't belong in the OBJ export anyway.
            continue

    obj_path = run_dir / "map.obj"
    if has_mesh:
        try:
            bpy.ops.wm.obj_export(
                filepath=str(obj_path),
                export_selected_objects=True,
                export_materials=True,
                # Write per-vertex colors as ``v X Y Z R G B`` lines so
                # the eroded-terrain biome attribute survives the round
                # trip to Three.js. Without this every vertex-color-
                # driven material in the scene degrades to its
                # static Principled BSDF Base Color in the MTL — which
                # for the eroded terrain is the unset 0.8 0.8 0.8
                # default and reads as "plain grey terrain" in the
                # browser viewer.
                export_colors=True,
                forward_axis="NEGATIVE_Z",
                up_axis="Y",
            )
        except RuntimeError:
            # Older Blender ops names — fall back gracefully.
            try:
                bpy.ops.export_scene.obj(  # type: ignore[attr-defined]
                    filepath=str(obj_path),
                    use_selection=True,
                    use_materials=True,
                )
            except Exception:
                obj_path = None  # type: ignore[assignment]

    _PHASE_HISTORY.append(phase_name)

    marker = run_dir / f"_phase_{phase_name}.json"
    marker.write_text(json.dumps({
        "phase": phase_name,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "obj_path": str(obj_path) if obj_path else None,
        "history": list(_PHASE_HISTORY),
    }, indent=2))
    return str(obj_path) if obj_path else None
