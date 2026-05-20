"""Render thumbnails for every factory archetype + named preset, then emit
``FACTORIES_GALLERY.md`` — a Markdown gallery of the whole catalog.

    python3 -m infinigen.maquette.pipeline.thumbnail_grid          # incremental
    python3 -m infinigen.maquette.pipeline.thumbnail_grid --refresh-all
    python3 -m infinigen.maquette.pipeline.thumbnail_grid --factory LowPolyBellFactory
    python3 -m infinigen.maquette.pipeline.thumbnail_grid --presets-only

What it produces:

  _artifacts/maquette/factory_thumbnails/<ClassName>__<label>.png
  _artifacts/maquette/FACTORIES_GALLERY.md

Why a sibling gallery instead of injecting into FACTORIES_GUIDE.md:
the guide is text-only and the LLM build pipeline currently consumes
it as a token-budgeted reference. The gallery is a human-and-multimodal
companion — separate file, separate concerns, easy to delete + regen.

How "what to render" is decided:

  1. Every named preset in ``factory_presets.ALL_PRESETS`` gets a thumb
  2. Every archetype value from ``_<X>_ARCHETYPES = (...)`` tuples in
     a factory module gets a thumb (parsed via AST — works without
     importing the factory file, so a broken module doesn't poison
     the run)
  3. A factory with neither presets nor archetype tuples gets ONE
     default thumb at factory_seed=0

Incremental by default — skips thumbnails whose PNG already exists.
``--refresh-all`` re-renders the whole set; ``--factory NAME`` limits
to one factory. The CLI is cheap to wire into a pre-commit hook later.
"""

from __future__ import annotations

import argparse
import ast
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .factories_guide import FORK_ROOT, _factory_files, _find_factory_class
from .preview import render_factory


THUMBNAIL_DIR = FORK_ROOT.parent / "factory_thumbnails"
GALLERY_PATH = FORK_ROOT / "infinigen" / "maquette" / "FACTORIES_GALLERY.md"
DEFAULT_SAMPLES = 24
DEFAULT_SIZE = 320


@dataclass
class RenderTarget:
    """One thumbnail to produce."""
    factory_name: str
    factory_file: Path
    label: str                            # filesystem-safe label
    kind: str                             # "preset" | "archetype" | "default"
    description: str = ""                 # short caption for the gallery
    archetype: str | None = None
    preset: str | None = None
    seed: int = 0


@dataclass
class FactoryEntry:
    """Aggregated render targets for one factory, used to build the gallery
    section for it."""
    factory_name: str
    factory_file: Path
    targets: list[RenderTarget] = field(default_factory=list)


# --- archetype discovery (AST — no factory import needed) -------------------


def _archetype_tuples_in(path: Path) -> list[tuple[str, list[str]]]:
    """Find ``_<X>_ARCHETYPES = (...)`` tuples in a factory module by AST,
    so a typo / runtime error in the factory doesn't prevent thumbnails
    from regenerating for the rest of the catalog. Returns
    [(tuple_name, [values, ...]), ...]."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return []
    out: list[tuple[str, list[str]]] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id.endswith("_ARCHETYPES"):
                if isinstance(node.value, (ast.Tuple, ast.List)):
                    values = [
                        elt.value
                        for elt in node.value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    ]
                    out.append((tgt.id, values))
    return out


def _primary_archetype_values(path: Path) -> list[str]:
    """Most factories with multiple archetype tuples have ONE that maps to
    the constructor kwarg name (e.g. building.py has both
    _BUILDING_ARCHETYPES and _ROOF_ARCHETYPES; the constructor takes
    building_archetype). Pick the first tuple whose name matches
    ``<MODULE_STEM>_ARCHETYPES`` (case-insensitive) — that's the
    convention every native factory follows."""
    tuples = _archetype_tuples_in(path)
    if not tuples:
        return []
    stem_upper = path.stem.upper()
    # First, exact prefix match.
    for name, values in tuples:
        bare = name.strip("_").replace("_ARCHETYPES", "")
        if bare.upper() == stem_upper:
            return values
    # Fallback: first tuple that starts with `_` (module-internal).
    for name, values in tuples:
        if name.startswith("_"):
            return values
    return tuples[0][1]


# --- target discovery -------------------------------------------------------


def _safe_label(text: str) -> str:
    """Filesystem-safe label component (kebab/underscore)."""
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in text)


def discover_targets(*, factory_filter: str | None = None,
                     presets_only: bool = False) -> list[FactoryEntry]:
    """Walk the catalog + presets and return one FactoryEntry per factory."""
    from infinigen.maquette.factory_presets import ALL_PRESETS

    entries: dict[str, FactoryEntry] = {}

    # 1. From factory modules: identify the class + its primary archetypes.
    for path in _factory_files(mode="low_poly"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        cls_info = _find_factory_class(tree)
        if cls_info is None:
            continue
        cls_name, _doc = cls_info
        if factory_filter and cls_name != factory_filter:
            continue

        entry = FactoryEntry(factory_name=cls_name, factory_file=path)
        entries[cls_name] = entry

        if presets_only:
            continue

        archetypes = _primary_archetype_values(path)
        for arch in archetypes:
            entry.targets.append(RenderTarget(
                factory_name=cls_name, factory_file=path,
                label=f"archetype__{_safe_label(arch)}",
                kind="archetype",
                description=arch,
                archetype=arch,
            ))

        if not archetypes:
            entry.targets.append(RenderTarget(
                factory_name=cls_name, factory_file=path,
                label="default", kind="default",
                description="default constructor",
            ))

    # 2. From the preset registry: append a preset target per (factory, preset).
    for cls_name, preset_dict in ALL_PRESETS.items():
        if factory_filter and cls_name != factory_filter:
            continue
        entry = entries.get(cls_name)
        if entry is None:
            # Presets registered for a factory whose module file we didn't
            # find — emit a synthetic entry so it still gets rendered.
            entry = FactoryEntry(factory_name=cls_name, factory_file=FORK_ROOT)
            entries[cls_name] = entry
        for preset_name in preset_dict:
            entry.targets.append(RenderTarget(
                factory_name=cls_name, factory_file=entry.factory_file,
                label=f"preset__{_safe_label(preset_name)}",
                kind="preset",
                description=preset_name,
                preset=preset_name,
            ))

    # Drop entries with no targets (filtered factories with neither
    # archetypes nor presets when presets_only=True).
    return [e for e in entries.values() if e.targets]


# --- rendering --------------------------------------------------------------


def thumbnail_path_for(factory_name: str, label: str) -> Path:
    return THUMBNAIL_DIR / f"{factory_name}__{label}.png"


def render_target(target: RenderTarget, *,
                  force: bool, samples: int, size: int,
                  blender_bin: str) -> tuple[bool, str]:
    """Render one thumbnail. Returns (success, message)."""
    out = thumbnail_path_for(target.factory_name, target.label)
    if out.is_file() and not force:
        return True, "cached"
    result = render_factory(
        factory_name=target.factory_name,
        out_png=out,
        seed=target.seed,
        archetype=target.archetype,
        preset=target.preset,
        samples=samples,
        size=size,
        blender_bin=blender_bin,
        timeout_seconds=180,
    )
    if result.returncode != 0:
        # Surface the inner script's FAIL: line if present.
        msg = (result.stdout or "") + (result.stderr or "")
        fail_line = next(
            (ln for ln in msg.splitlines() if ln.startswith(("FAIL:", "RuntimeError"))),
            f"blender exit {result.returncode}",
        )
        return False, fail_line[:200]
    return True, "rendered"


# --- gallery markdown -------------------------------------------------------


_GALLERY_HEADER = """\
# Maquette · Factory Gallery

Autogenerated thumbnail gallery for every factory archetype + named
preset in the catalog. Regenerate with:

```bash
python3 -m infinigen.maquette.pipeline.thumbnail_grid --refresh-all
```

Companion to ``FACTORIES_GUIDE.md`` (text-only reference). Use this
file to *look at* the catalog; use the guide to *read* the constructor
signatures.

"""


def build_gallery_md(entries: list[FactoryEntry], *, cols: int = 4) -> str:
    """Build the gallery as one table per factory. Each row holds up to
    ``cols`` thumbnails. Caption under each image is the archetype /
    preset name."""
    parts = [_GALLERY_HEADER]
    for entry in sorted(entries, key=lambda e: e.factory_name):
        parts.append(f"## `{entry.factory_name}`")
        parts.append("")
        # Sort: archetypes first, then presets, then default.
        kind_order = {"archetype": 0, "preset": 1, "default": 2}
        targets = sorted(
            entry.targets,
            key=lambda t: (kind_order.get(t.kind, 9), t.label),
        )
        for chunk_start in range(0, len(targets), cols):
            chunk = targets[chunk_start:chunk_start + cols]
            img_row = "| " + " | ".join(
                f"![{t.description}]({_relative_thumb_path(t)})"
                for t in chunk
            ) + " |"
            sep_row = "|" + "|".join([":---:"] * len(chunk)) + "|"
            cap_row = "| " + " | ".join(
                f"**{t.kind}**: `{t.description}`"
                for t in chunk
            ) + " |"
            parts.append(img_row)
            parts.append(sep_row)
            parts.append(cap_row)
            parts.append("")
    return "\n".join(parts)


def _relative_thumb_path(target: RenderTarget) -> str:
    """Path from the gallery .md location to the thumbnail PNG. Uses
    POSIX separators (Markdown is path-agnostic but ../ traversal is
    cleaner with forward slashes)."""
    thumb = thumbnail_path_for(target.factory_name, target.label)
    try:
        rel = thumb.relative_to(GALLERY_PATH.parent)
        return str(rel).replace("\\", "/")
    except ValueError:
        # GALLERY_PATH is under infinigen/maquette/ while thumbs live in
        # _artifacts/maquette/. Use a relative `../../...` traversal.
        return str(Path("..") / ".." / ".." / thumb.relative_to(FORK_ROOT.parent)).replace("\\", "/")


# --- entry point ------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m infinigen.maquette.pipeline.thumbnail_grid",
        description="Render thumbnails + emit FACTORIES_GALLERY.md.",
    )
    parser.add_argument("--factory", default=None,
                        help="Limit to one factory class")
    parser.add_argument("--refresh-all", action="store_true",
                        help="Re-render thumbnails even if cached")
    parser.add_argument("--presets-only", action="store_true",
                        help="Skip archetype renders; only presets")
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE)
    parser.add_argument("--blender", default="blender")
    parser.add_argument("--no-gallery", action="store_true",
                        help="Render thumbnails but don't rewrite the gallery .md")
    parser.add_argument("--gallery-only", action="store_true",
                        help="Skip rendering; just rewrite the gallery .md "
                             "from whatever thumbnails already exist on disk")
    args = parser.parse_args(argv)

    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

    entries = discover_targets(
        factory_filter=args.factory,
        presets_only=args.presets_only,
    )
    n_targets = sum(len(e.targets) for e in entries)
    print(f"[thumbnail_grid] discovered {len(entries)} factories, "
          f"{n_targets} render targets")

    if not args.gallery_only:
        n_done = 0
        n_cached = 0
        n_failed = 0
        t0 = time.time()
        for entry in entries:
            for target in entry.targets:
                ok, msg = render_target(
                    target,
                    force=args.refresh_all,
                    samples=args.samples,
                    size=args.size,
                    blender_bin=args.blender,
                )
                if not ok:
                    n_failed += 1
                    print(f"  [FAIL]   {target.factory_name}::{target.label}: {msg}",
                          file=sys.stderr)
                elif msg == "cached":
                    n_cached += 1
                else:
                    n_done += 1
                    elapsed = time.time() - t0
                    rate = (n_done + n_cached) / max(elapsed, 0.001)
                    print(f"  [ok]     {target.factory_name}::{target.label} "
                          f"({n_done + n_cached}/{n_targets}, "
                          f"{rate:.2f}/s)")
        print(f"[thumbnail_grid] rendered={n_done} cached={n_cached} "
              f"failed={n_failed} in {time.time() - t0:.1f}s")
        if n_failed and n_done == 0 and n_cached == 0:
            return 1

    if not args.no_gallery:
        # Trim entries to only ones whose thumbnails actually exist on
        # disk now — otherwise the gallery would point at missing files.
        rendered_entries: list[FactoryEntry] = []
        for entry in entries:
            extant = [
                t for t in entry.targets
                if thumbnail_path_for(t.factory_name, t.label).is_file()
            ]
            if extant:
                rendered_entries.append(
                    FactoryEntry(entry.factory_name, entry.factory_file, extant)
                )
        md = build_gallery_md(rendered_entries)
        GALLERY_PATH.write_text(md)
        print(f"[thumbnail_grid] wrote {GALLERY_PATH} "
              f"({len(rendered_entries)} factories)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
