"""Spawn a `claude -p` subprocess to implement a missing factory.

The implementer-Claude has full tool access (Read/Write/Edit/Bash) to
the working tree, so we delegate the work entirely. The implementer
must:

  - read 2-3 existing factories to learn the conventions
  - implement the new factory at the right path
  - add it to both __init__.py files
  - write + run a smoke test, confirming it spawns successfully

We don't try to validate the implementation here beyond running the
smoke test the implementer is told to write — if the smoke runs
green, we trust the implementation. Caller (pipeline cli) regenerates
the FACTORIES_GUIDE.md after each implementation so the next run
sees the new factory.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

from .factories_guide import FORK_ROOT


@dataclass
class ImplementationResult:
    factory_name: str
    success: bool
    output: str
    smoke_log: str = ""


_IMPLEMENTER_PROMPT_TEMPLATE = """\
You are the factory-implementer subprocess of the Maquette pipeline.
You have full tool access (Read, Write, Edit, Bash). Your task is to
implement a single new low-poly factory in the Maquette fork at
`/home/tang/songe/_artifacts/maquette/infinigen-fork`.

## Spec

Factory class name: `{factory_name}`
Purpose: {spec}

## Conventions to follow

Read 2-3 existing factories before writing the new one — the closest
analog factories are usually under
`infinigen/maquette/factories/native/`. Match their style precisely:

  - module-level `_<NAME>_ARCHETYPES` tuple of allowed archetype strings
  - module-level `_ARCHETYPE_DEFAULTS` dict mapping each archetype to
    its default knob values
  - subclass `infinigen.core.placement.factory.AssetFactory`
  - implement `create_placeholder` (returns a lightweight Empty —
    spawn_asset deletes the placeholder, so it must NOT be the same
    object as the asset)
  - implement `create_asset(self, placeholder=None, **kwargs)` — build
    the geometry via bmesh, write to a new mesh, link to the scene,
    set polygon material indices via slot_ranges, and call
    `apply_palette_slots(obj, [color1, color2, ...])` from
    `infinigen.maquette.materials`
  - palette keys are listed in `infinigen/maquette/palette.py` —
    `wood`, `rust_metal`, `stucco`, `rock_warm`, `rock_cool`,
    `rock_pale`, `rock_shadow`, `accent_red`, `foliage_pine`, etc.
    Do not invent new palette keys; use existing ones.

## File layout

  - Implementation: `infinigen/maquette/factories/native/{module_stem}.py`
  - Update `infinigen/maquette/factories/native/__init__.py` to import
    + export the new factory class (alphabetical order in __all__)
  - Update `infinigen/maquette/factories/__init__.py` similarly

## Smoke test

After implementation, write a smoke test at `/tmp/smoke_{module_stem}.py`
that:

  - sets up sys.path to include the fork
  - imports the new factory
  - wipes the scene + adds a ground plane
  - instantiates the factory once per archetype
  - calls `create_asset(placeholder=None)` on each
  - prints face count + slot count per archetype, and asserts both > 0

Run the smoke test via:

    blender --background --python /tmp/smoke_{module_stem}.py

Confirm it prints "X/X passed" with no Python tracebacks. Iterate if
needed.

## Output

When the implementation + smoke test both pass, output ONE line:

    DONE: infinigen/maquette/factories/native/{module_stem}.py

If it fails after reasonable retries, output:

    FAILED: <one-line reason>

Do not output any other text on those final lines.

## Why this matters

The Maquette pipeline asked for this factory while building a scene
and wrote a `# REQUESTED_ASSET:` marker. Once you implement it, the
pipeline can re-run the build script with the new factory available,
closing the empirical loop that's documented in `SCENE_PROMPTS.md`.

Begin.
"""


def _factory_to_module_stem(factory_name: str) -> str:
    """LowPolyPalmTreeFactory → palm_tree."""
    name = factory_name
    if name.startswith("LowPoly"):
        name = name[len("LowPoly"):]
    if name.endswith("Factory"):
        name = name[: -len("Factory")]
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and not name[i - 1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


_DONE_RE = re.compile(r"^DONE:\s*(?P<path>.+?)\s*$", re.MULTILINE)
_FAILED_RE = re.compile(r"^FAILED:\s*(?P<reason>.+?)\s*$", re.MULTILINE)


def implement_factory(factory_name: str, spec: str,
                      *, model: str | None = None,
                      timeout_seconds: int = 900) -> ImplementationResult:
    """Implement one missing factory via a `claude -p` subprocess.

    The subprocess is expected to run agentically (Read/Write/Edit/Bash)
    and finalize with a `DONE: <path>` or `FAILED: <reason>` line."""
    if shutil.which("claude") is None:
        return ImplementationResult(
            factory_name=factory_name, success=False,
            output="`claude` CLI not on PATH",
        )
    module_stem = _factory_to_module_stem(factory_name)
    prompt = _IMPLEMENTER_PROMPT_TEMPLATE.format(
        factory_name=factory_name, spec=spec, module_stem=module_stem,
    )
    cmd = ["claude", "-p"]
    if model:
        cmd.extend(["--model", model])
    # Implementer needs filesystem write access; pass-through stdio inherits
    # whatever permissions the parent shell has.
    proc = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        capture_output=True,
        cwd=FORK_ROOT,
        timeout=timeout_seconds,
    )
    output = proc.stdout + ("\n--- stderr ---\n" + proc.stderr if proc.stderr else "")

    if proc.returncode != 0:
        return ImplementationResult(
            factory_name=factory_name, success=False, output=output,
        )

    done_match = _DONE_RE.search(proc.stdout)
    failed_match = _FAILED_RE.search(proc.stdout)
    if done_match and not failed_match:
        return ImplementationResult(
            factory_name=factory_name, success=True, output=output,
        )
    return ImplementationResult(
        factory_name=factory_name, success=False, output=output,
    )
