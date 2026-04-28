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
                     timeout_seconds: int = 600) -> ExecutionResult:
    """Run `blender --background --python script.py` with MAQUETTE_OUT_DIR
    set so the script writes to the right place."""
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
    return ExecutionResult(
        return_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        out_dir=out_dir,
        render_path=render_path,
        blend_path=blend_path,
        exists=render_path.is_file() and blend_path.is_file(),
    )
