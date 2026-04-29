"""Drive `claude -p` to generate a Blender build script for a prompt.

The runner is the single Claude invocation. It composes a context bundle
(FACTORIES_GUIDE.md + one canonical example) + the user prompt + system
instructions, then invokes `claude -p "<bundle>"` and parses the response
to extract the Python script.

Why `claude -p` instead of the API directly: keeps a single dependency
(`claude` CLI is already on the user's machine), inherits the user's
auth, and lets us swap in any Claude Code-compatible backend without
rewiring the pipeline.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .factories_guide import FORK_ROOT, MAQUETTE_DIR, write_guide

EXAMPLE_PATH = MAQUETTE_DIR / "pipeline" / "examples" / "medieval_village.py"


@dataclass
class GenerationResult:
    raw_response: str          # everything Claude returned
    extracted_script: str      # the Python script we'll run
    requested_assets: list[str]  # `# REQUESTED_ASSET: ...` lines


_SYSTEM_PROMPT = """\
You are the scene-build subprocess of the Maquette pipeline. You receive
a customer prompt for a 3D scene and a catalog of available factories.
You output a SINGLE Python script that, when run via `blender --background
--python script.py`, produces a stylized low-poly scene matching the
prompt and writes the render to `$MAQUETTE_OUT_DIR/scene.png` and a
.blend to `$MAQUETTE_OUT_DIR/scene.blend`.

CRITICAL RULES:

1. Output ONLY the Python script. No commentary before or after.
   Wrap the entire script in a ```python ... ``` fenced code block.
   Do not include any thinking or planning text outside the block.

2. Follow the canonical skeleton in the factory catalog (sys.path setup,
   ground plane, factory spawns, camera, sun, world bg, render to
   $MAQUETTE_OUT_DIR/scene.{png,blend}).

3. Only use factories that exist in the catalog below. If you wish a
   factory existed, write a `# REQUESTED_ASSET: <Name> — <purpose>`
   comment at the top of the script and BUILD THE SCENE ANYWAY using
   the closest existing factory as a stand-in. Do not refuse to build.

4. Use varied archetypes, scales, and rotations to avoid a uniform
   "instanced" look. Pick a lighting recipe that matches the prompt's
   mood (dawn, midday, golden hour, twilight, wasteland).

5. Keep total object count under ~150 to render in <30s.

6. DO NOT add `ShaderNodeVolumeScatter`, `ShaderNodeVolumeAbsorption`,
   any world-volume effects, or fog/mist/haze volumetrics. They render
   pure black at the low sample counts (32-48) we use. If the prompt
   mentions "fog", "mist", "haze", "dust", express it through the world
   background colour and sun warmth/dimness instead — never via a Volume
   shader.

7. Use the standard `archetype` parameter names from the catalog —
   `building_archetype`, `foliage_archetype`, `trunk_archetype`,
   `fence_archetype`, etc. There is no plain `archetype` kwarg on any
   factory; passing it will cause a runtime error.

8. The ground plane material should set `Base Color` directly. Do not
   add image textures, noise nodes, or shader graphs to materials —
   the Maquette aesthetic is solid flat colour per slot.

9. LIVE PROGRESS — call `checkpoint('<phase>')` at each major build
   boundary so the frontend's 3D viewer can show the scene evolving
   while the script runs. Required calls (skip any that don't apply):
     - after ground/terrain is in place:        checkpoint('terrain')
     - after primary foliage (trees, bushes):    checkpoint('foliage')
     - after buildings / structures:             checkpoint('structures')
     - after small props / scatter / fences:     checkpoint('props')
     - just before render:                       checkpoint('final')
   Import once near the top of the script:
     from infinigen.maquette.runtime.checkpoint import checkpoint
   Each call exports the current scene to map.obj — keep them at
   coherent visual milestones (don't checkpoint inside a tight loop).
"""


def _read_text(p: Path) -> str:
    return p.read_text() if p.exists() else ""


def build_prompt(user_prompt: str, *, regenerate_guide: bool = True) -> str:
    """Assemble the full prompt: system instructions + factory catalog +
    canonical example + user prompt."""
    if regenerate_guide:
        write_guide()
    guide = _read_text(MAQUETTE_DIR / "FACTORIES_GUIDE.md")
    example = _read_text(EXAMPLE_PATH)

    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"## Factory catalog\n\n{guide}\n\n"
        f"## Canonical example — \"medieval village by a stream\"\n\n"
        f"This is the gold-standard build script you should pattern-match\n"
        f"on. Same structure (wipe → ground → spawns → camera → sun → world\n"
        f"→ render to $MAQUETTE_OUT_DIR), different content per prompt.\n\n"
        f"```python\n{example}\n```\n\n"
        f"## YOUR TASK\n\n"
        f"User prompt: {user_prompt}\n\n"
        f"Generate the build script."
    )


_CODE_FENCE = re.compile(r"```python\s*\n(.*?)\n```", re.DOTALL)
_REQUESTED_LINE = re.compile(
    r"^\s*#\s*REQUESTED_ASSET:\s*(?P<rest>.+?)\s*$", re.MULTILINE
)


def extract_script(response: str) -> str:
    """Pull the Python script out of Claude's response. Handles fenced
    blocks; raises if none found."""
    match = _CODE_FENCE.search(response)
    if not match:
        # Fallback: if the response *is* a Python script (no markdown), use
        # it as-is. Heuristic: starts with "import" / "from" / a docstring.
        stripped = response.strip()
        first = stripped.splitlines()[0] if stripped else ""
        if first.startswith(("import ", "from ", '"""', "'''")):
            return stripped
        raise ValueError(
            "no ```python code block in Claude response and response doesn't "
            "look like a bare script. First 200 chars:\n" + stripped[:200]
        )
    return match.group(1)


def extract_requested_assets(script: str) -> list[str]:
    """Pull `# REQUESTED_ASSET: ...` markers from the script."""
    return [m.group("rest").strip() for m in _REQUESTED_LINE.finditer(script)]


def call_claude(prompt: str, *, model: str | None = None,
                timeout_seconds: int = 300) -> str:
    """Run `claude -p <prompt>` and return stdout. The prompt is passed via
    stdin to avoid shell-arg-length limits."""
    if shutil.which("claude") is None:
        raise RuntimeError(
            "`claude` CLI not found on PATH. Install Claude Code or "
            "ensure the binary is in PATH for this user."
        )
    cmd = ["claude", "-p"]
    if model:
        cmd.extend(["--model", model])
    proc = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"`claude` exited {proc.returncode}.\n"
            f"stderr:\n{proc.stderr}\nstdout (first 2k):\n{proc.stdout[:2000]}"
        )
    return proc.stdout


def generate(user_prompt: str, *, model: str | None = None,
             timeout_seconds: int = 300,
             regenerate_guide: bool = True) -> GenerationResult:
    """End-to-end: prompt → Claude → extracted script."""
    full_prompt = build_prompt(user_prompt, regenerate_guide=regenerate_guide)
    response = call_claude(full_prompt, model=model, timeout_seconds=timeout_seconds)
    script = extract_script(response)
    requested = extract_requested_assets(script)
    return GenerationResult(
        raw_response=response,
        extracted_script=script,
        requested_assets=requested,
    )
