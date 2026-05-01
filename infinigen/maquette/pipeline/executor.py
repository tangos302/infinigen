"""Run the generated build script via headless Blender, capture outputs."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExecutionResult:
    return_code: int
    stdout: str
    stderr: str
    out_dir: Path
    render_path: Path
    blend_path: Path
    exists: bool   # whether scene.png + scene.blend both exist on disk


def run_build_script(script_path: Path, out_dir: Path,
                     *, blender_bin: str = "blender",
                     timeout_seconds: int = 600,
                     multi_angle: bool = True) -> ExecutionResult:
    """Run `blender --background --python script.py` with MAQUETTE_OUT_DIR
    set so the script writes to the right place.

    If ``multi_angle`` is True (default) the build is followed by 3
    alternate-angle renders (camera rotated 90°/180°/270° around the
    world Z axis) and a 2×2 grid composite — surfaces hollow scenes
    that look fine from one angle but empty everywhere else. Adds
    ~30-60s to the total runtime.
    """
    if shutil.which(blender_bin) is None:
        raise RuntimeError(
            f"`{blender_bin}` not found on PATH. Install Blender 4.2 or "
            f"set a different binary path."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["MAQUETTE_OUT_DIR"] = str(out_dir)
    proc = subprocess.run(
        [blender_bin, "--background", "--python", str(script_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    render_path = out_dir / "scene.png"
    blend_path = out_dir / "scene.blend"

    # Multi-angle pass — only if the hero render succeeded.
    if multi_angle and render_path.is_file() and blend_path.is_file():
        try:
            from infinigen.maquette.runtime.multi_angle import render_multi_angle
            render_multi_angle(
                blend_path=blend_path,
                out_dir=out_dir,
                blender_bin=blender_bin,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            # Non-fatal — hero render still ships even if alts fail.
            print(f"[executor] multi-angle skipped ({type(exc).__name__}: {exc})")

    return ExecutionResult(
        return_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        out_dir=out_dir,
        render_path=render_path,
        blend_path=blend_path,
        exists=render_path.is_file() and blend_path.is_file(),
    )
