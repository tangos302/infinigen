"""CLI entry point for the Maquette pipeline.

Usage::

    python -m infinigen.maquette.pipeline.cli "small medieval village by a stream"

    python -m infinigen.maquette.pipeline.cli "Mad Max citadel" \\
        --out _artifacts/maquette/pipeline_runs/citadel \\
        --model claude-sonnet-4-6 \\
        --no-render

Flags:

    --out <path>       output directory; defaults to
                       _artifacts/maquette/pipeline_runs/<timestamp>
    --model <name>     Claude model override (passed to `claude --model`)
    --no-render        skip the Blender render step (useful to inspect
                       the generated script first)
    --local            after-script run, if any REQUESTED_ASSET, invoke
                       a second Claude pass to implement the missing
                       factory and re-run the build (NOT YET IMPLEMENTED
                       in phase 1)
    --blender <bin>    Blender binary path; default `blender` on PATH

The output directory contains:

    build.py           the script Claude generated
    raw_response.md    Claude's raw output (for debugging)
    scene.png          render
    scene.blend        scene file
    requested_assets   list of `# REQUESTED_ASSET:` lines extracted

The project-level `requested_assets.md` (one level up from the run dir)
gets appended with any new gap requests, so they accumulate across runs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from . import gap_tracker, runner, executor


DEFAULT_RUNS_ROOT = (
    runner.FORK_ROOT.parent / "pipeline_runs"
)


def _slugify(prompt: str, max_len: int = 32) -> str:
    """A short filesystem-safe stem from the prompt."""
    s = "".join(c.lower() if c.isalnum() else "_" for c in prompt)
    s = "_".join(filter(None, s.split("_")))
    return s[:max_len]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m infinigen.maquette.pipeline.cli",
        description="Generate a low-poly stylized scene from a prompt.",
    )
    parser.add_argument("prompt", help="The customer prompt.")
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Output directory. Default: pipeline_runs/<timestamp>_<slug>",
    )
    parser.add_argument(
        "--model", default=None,
        help="Claude model override (e.g., claude-sonnet-4-6).",
    )
    parser.add_argument(
        "--no-render", action="store_true",
        help="Skip the Blender render step.",
    )
    parser.add_argument(
        "--local", action="store_true",
        help="(phase 2) Implement missing factories on the fly.",
    )
    parser.add_argument(
        "--blender", default="blender",
        help="Blender binary path on PATH or absolute. Default: `blender`.",
    )
    parser.add_argument(
        "--timeout", type=int, default=300,
        help="Per-step timeout in seconds. Default: 300.",
    )
    args = parser.parse_args(argv)

    # Output dir: <pipeline_runs>/<timestamp>_<slug>
    if args.out is None:
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = _slugify(args.prompt)
        args.out = DEFAULT_RUNS_ROOT / f"{ts}_{slug}"
    args.out.mkdir(parents=True, exist_ok=True)

    # Step 1 — Claude generates the script
    print(f"[maquette] generating script for prompt: {args.prompt!r}")
    print(f"[maquette] output dir: {args.out}")
    try:
        result = runner.generate(
            args.prompt,
            model=args.model,
            timeout_seconds=args.timeout,
        )
    except Exception as e:
        print(f"[maquette] generation failed: {e}", file=sys.stderr)
        return 2

    # Persist raw response + script
    (args.out / "raw_response.md").write_text(result.raw_response)
    build_py = args.out / "build.py"
    build_py.write_text(result.extracted_script)
    print(f"[maquette] wrote {build_py}")

    # Step 2 — Append any REQUESTED_ASSET entries to the tracker
    if result.requested_assets:
        print(f"[maquette] {len(result.requested_assets)} requested asset(s):")
        for r in result.requested_assets:
            print(f"  - {r}")
        gap_tracker.append(result.requested_assets)
    (args.out / "requested_assets.txt").write_text(
        "\n".join(result.requested_assets) + ("\n" if result.requested_assets else "")
    )

    # Step 3 (optional) — render via Blender
    if args.no_render:
        print("[maquette] --no-render set, stopping after script generation.")
        return 0

    if args.local:
        print(
            "[maquette] WARNING: --local mode not implemented in phase 1. "
            "Running the build script as-is; missing factories will fail."
        )

    print(f"[maquette] running build via Blender ({args.blender})…")
    exec_result = executor.run_build_script(
        build_py, args.out,
        blender_bin=args.blender,
        timeout_seconds=args.timeout,
    )
    (args.out / "blender_stdout.txt").write_text(exec_result.stdout)
    (args.out / "blender_stderr.txt").write_text(exec_result.stderr)

    if exec_result.return_code != 0 or not exec_result.exists:
        print(
            f"[maquette] build failed (rc={exec_result.return_code}, "
            f"render exists={exec_result.render_path.is_file()}, "
            f"blend exists={exec_result.blend_path.is_file()}).",
            file=sys.stderr,
        )
        print("---stderr tail---", file=sys.stderr)
        print(exec_result.stderr[-2000:], file=sys.stderr)
        return 3

    print(f"[maquette] OK · render: {exec_result.render_path}")
    print(f"[maquette] OK · blend:  {exec_result.blend_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
