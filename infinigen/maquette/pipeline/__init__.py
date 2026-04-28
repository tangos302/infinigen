"""Maquette pipeline — single-pass prompt-to-scene generator.

Customer types a prompt ("Mad Max citadel"); a single Claude Code
invocation reads a generated FACTORIES_GUIDE catalog of available
low-poly factories + a few reference build scripts, and produces a
Blender Python script that constructs the scene. The pipeline runs
the script via headless Blender, capturing render + .blend.

Two modes:

  --remote (default): missing-factory requests get appended to
    requested_assets.md for a separate batch Claude pass to implement.

  --local: a second Claude pass implements the missing factory in-band,
    smoke-tests it, and re-runs the build script. Slower per-prompt
    but the bank grows organically scene by scene.

This is the single-shot pipeline (vs. the multi-stage Northstar /
Atelier pipelines in songe-core). Goals match the empirical loop
already used in SCENE_PROMPTS.md attempt log: prompt → build → identify
gaps → fill gaps → re-run.

Codename for memory / cross-reference: Maquette is the procedural-mesh
codename; this pipeline doesn't rename it.
"""

from .cli import main as cli_main

__all__ = ["cli_main"]
