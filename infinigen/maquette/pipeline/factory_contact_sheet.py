"""Render a multi-variant contact sheet for one Maquette factory.

This is the Phase-0 QA tool for Songe Forge v2. It uses the existing
single-factory preview renderer for each cell, then composes the rendered
PNGs into one contact sheet with seed/archetype/preset labels and mesh stats.

Typical usage from the Songe repo root::

    PYTHONPATH=/home/tang/songe/_artifacts/maquette/infinigen-fork \
    python3 -m infinigen.maquette.pipeline.factory_contact_sheet \
      --factory LowPolyPalmTreeFactory --seeds 0,1,2,3 --samples 16 --size 512

Outputs default to ``gen/factory_showcases/<FactoryName>/``.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .factories_guide import FORK_ROOT
from .preview import render_factory
from .thumbnail_grid import discover_targets


def _repo_root() -> Path:
    if FORK_ROOT.parent.name == "maquette" and FORK_ROOT.parent.parent.name == "_artifacts":
        return FORK_ROOT.parent.parent.parent
    return Path.cwd()


DEFAULT_OUT_ROOT = _repo_root() / "gen" / "factory_showcases"


@dataclass(frozen=True)
class ContactTarget:
    label: str
    kind: str
    archetype: str | None = None
    preset: str | None = None


@dataclass
class CellResult:
    target: ContactTarget
    seed: int
    image_path: Path
    metadata_path: Path
    status: str
    message: str
    metadata: dict | None = None


def _parse_csv_values(text: str | None) -> list[str]:
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def _parse_seeds(text: str | None, *, count: int, start: int) -> list[int]:
    if text:
        return [int(part.strip()) for part in text.split(",") if part.strip()]
    return list(range(int(start), int(start) + int(count)))


def _safe_label(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in text)


def _targets_for_factory(
    factory_name: str,
    *,
    archetypes: list[str],
    presets: list[str],
    include_presets: bool,
) -> list[ContactTarget]:
    if archetypes and presets:
        raise ValueError("--archetypes and --presets are mutually exclusive")
    if archetypes:
        return [
            ContactTarget(
                label=f"archetype__{_safe_label(archetype)}",
                kind="archetype",
                archetype=archetype,
            )
            for archetype in archetypes
        ]
    if presets:
        return [
            ContactTarget(
                label=f"preset__{_safe_label(preset)}",
                kind="preset",
                preset=preset,
            )
            for preset in presets
        ]

    entries = discover_targets(factory_filter=factory_name)
    if not entries:
        return [ContactTarget(label="default", kind="default")]

    discovered = entries[0].targets
    preset_targets = [target for target in discovered if target.kind == "preset"]
    archetype_targets = [target for target in discovered if target.kind == "archetype"]
    default_targets = [target for target in discovered if target.kind == "default"]

    selected = preset_targets if preset_targets and include_presets else archetype_targets
    if not selected:
        selected = default_targets or preset_targets or discovered[:1]

    return [
        ContactTarget(
            label=target.label,
            kind=target.kind,
            archetype=target.archetype,
            preset=target.preset,
        )
        for target in selected
    ]


def _load_metadata(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _render_cells(
    *,
    factory_name: str,
    targets: list[ContactTarget],
    seeds: list[int],
    out_dir: Path,
    samples: int,
    size: int,
    blender_bin: str,
    timeout: int,
    refresh: bool,
) -> list[CellResult]:
    cells: list[CellResult] = []
    cell_dir = out_dir / "cells"
    cell_dir.mkdir(parents=True, exist_ok=True)
    for target in targets:
        for seed in seeds:
            stem = f"{target.label}__seed_{seed:04d}"
            image_path = cell_dir / f"{stem}.png"
            metadata_path = cell_dir / f"{stem}.json"
            if (
                image_path.is_file()
                and metadata_path.is_file()
                and not refresh
            ):
                cells.append(CellResult(
                    target=target,
                    seed=seed,
                    image_path=image_path,
                    metadata_path=metadata_path,
                    status="cached",
                    message="cached",
                    metadata=_load_metadata(metadata_path),
                ))
                continue
            try:
                result = render_factory(
                    factory_name=factory_name,
                    out_png=image_path,
                    seed=seed,
                    archetype=target.archetype,
                    preset=target.preset,
                    metadata_path=metadata_path,
                    samples=samples,
                    size=size,
                    blender_bin=blender_bin,
                    timeout_seconds=timeout,
                )
            except Exception as exc:
                cells.append(CellResult(
                    target=target,
                    seed=seed,
                    image_path=image_path,
                    metadata_path=metadata_path,
                    status="failed",
                    message=str(exc),
                ))
                continue
            if result.returncode != 0:
                msg = (result.stdout or "") + "\n" + (result.stderr or "")
                fail_line = next(
                    (
                        line
                        for line in msg.splitlines()
                        if line.startswith(("FAIL:", "RuntimeError", "Traceback"))
                    ),
                    f"blender exit {result.returncode}",
                )
                cells.append(CellResult(
                    target=target,
                    seed=seed,
                    image_path=image_path,
                    metadata_path=metadata_path,
                    status="failed",
                    message=fail_line[:300],
                ))
                continue
            if not image_path.is_file():
                msg = (result.stdout or "") + "\n" + (result.stderr or "")
                fail_line = next(
                    (
                        line
                        for line in msg.splitlines()
                        if line.startswith(("FAIL:", "RuntimeError", "Traceback"))
                    ),
                    "render completed but did not write output image",
                )
                cells.append(CellResult(
                    target=target,
                    seed=seed,
                    image_path=image_path,
                    metadata_path=metadata_path,
                    status="failed",
                    message=fail_line[:300],
                ))
                continue
            cells.append(CellResult(
                target=target,
                seed=seed,
                image_path=image_path,
                metadata_path=metadata_path,
                status="rendered",
                message="rendered",
                metadata=_load_metadata(metadata_path),
            ))
    return cells


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textbbox((0, 0), candidate)[2] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _cell_label(cell: CellResult) -> tuple[str, str]:
    target_name = cell.target.preset or cell.target.archetype or "default"
    primary = f"{cell.target.kind}: {target_name} | seed {cell.seed}"
    stats = ((cell.metadata or {}).get("stats") or {})
    if not stats:
        return primary, cell.status
    secondary = (
        f"{stats.get('polygons', '?')} faces, "
        f"{stats.get('vertices', '?')} verts, "
        f"bbox {stats.get('bbox_size', '?')}"
    )
    return primary, secondary


def _compose_contact_sheet(
    *,
    factory_name: str,
    cells: list[CellResult],
    out_png: Path,
    columns: int,
    cell_size: int,
) -> None:
    successful = [cell for cell in cells if cell.status != "failed" and cell.image_path.is_file()]
    if not successful:
        raise RuntimeError("no successful cells to compose")

    columns = max(1, int(columns))
    rows = math.ceil(len(cells) / columns)
    label_h = 72
    margin = 18
    gutter = 12
    header_h = 74
    sheet_w = margin * 2 + columns * cell_size + (columns - 1) * gutter
    sheet_h = header_h + margin + rows * (cell_size + label_h) + (rows - 1) * gutter + margin
    sheet = Image.new("RGB", (sheet_w, sheet_h), (236, 235, 229))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    draw.rectangle((0, 0, sheet_w, header_h), fill=(32, 34, 31))
    draw.text((margin, 16), f"Songe Forge v2 contact sheet - {factory_name}", fill=(245, 244, 236), font=font)
    rendered = sum(1 for cell in cells if cell.status in {"rendered", "cached"})
    failed = sum(1 for cell in cells if cell.status == "failed")
    draw.text((margin, 40), f"{rendered} rendered/cached | {failed} failed", fill=(190, 190, 180), font=font)

    for index, cell in enumerate(cells):
        row = index // columns
        col = index % columns
        x = margin + col * (cell_size + gutter)
        y = header_h + margin + row * (cell_size + label_h + gutter)
        draw.rectangle((x - 1, y - 1, x + cell_size + 1, y + cell_size + label_h + 1), outline=(188, 186, 174))
        if cell.status == "failed" or not cell.image_path.is_file():
            draw.rectangle((x, y, x + cell_size, y + cell_size), fill=(82, 70, 67))
            draw.text((x + 12, y + 12), "FAILED", fill=(255, 230, 210), font=font)
            for line_index, line in enumerate(_fit_text(draw, cell.message, cell_size - 24)[:8]):
                draw.text((x + 12, y + 38 + line_index * 14), line, fill=(250, 220, 210), font=font)
        else:
            img = Image.open(cell.image_path).convert("RGB")
            img.thumbnail((cell_size, cell_size), Image.Resampling.LANCZOS)
            px = x + (cell_size - img.width) // 2
            py = y + (cell_size - img.height) // 2
            draw.rectangle((x, y, x + cell_size, y + cell_size), fill=(58, 58, 55))
            sheet.paste(img, (px, py))

        primary, secondary = _cell_label(cell)
        label_y = y + cell_size + 8
        draw.text((x + 8, label_y), primary[:64], fill=(36, 36, 32), font=font)
        for line_index, line in enumerate(_fit_text(draw, secondary, cell_size - 16)[:2]):
            draw.text((x + 8, label_y + 18 + line_index * 14), line, fill=(84, 82, 74), font=font)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png)


def _write_manifest(
    *,
    factory_name: str,
    targets: list[ContactTarget],
    seeds: list[int],
    cells: list[CellResult],
    out_png: Path,
    manifest_path: Path,
) -> None:
    manifest = {
        "factory": factory_name,
        "targets": [target.__dict__ for target in targets],
        "seeds": seeds,
        "contact_sheet": str(out_png),
        "counts": {
            "total": len(cells),
            "rendered_or_cached": sum(1 for cell in cells if cell.status in {"rendered", "cached"}),
            "failed": sum(1 for cell in cells if cell.status == "failed"),
        },
        "cells": [
            {
                "label": cell.target.label,
                "kind": cell.target.kind,
                "archetype": cell.target.archetype,
                "preset": cell.target.preset,
                "seed": cell.seed,
                "status": cell.status,
                "message": cell.message,
                "image_path": str(cell.image_path),
                "metadata_path": str(cell.metadata_path),
                "metadata": cell.metadata,
            }
            for cell in cells
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m infinigen.maquette.pipeline.factory_contact_sheet",
        description="Render a Songe Forge v2 contact sheet for one factory.",
    )
    parser.add_argument("--factory", required=True)
    parser.add_argument("--seeds", default=None, help="Comma-separated seed list, e.g. 0,1,2,3")
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--count", type=int, default=4, help="Seed count when --seeds is omitted")
    parser.add_argument("--archetypes", default=None, help="Comma-separated archetype values")
    parser.add_argument("--presets", default=None, help="Comma-separated preset names")
    parser.add_argument("--include-presets", action="store_true", default=True)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--size", type=int, default=512, help="Individual preview render size")
    parser.add_argument("--cell-size", type=int, default=320, help="Contact-sheet cell image size")
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--blender", default="blender")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)

    if shutil.which(args.blender) is None:
        print(f"FAIL: blender executable not found: {args.blender}", file=sys.stderr)
        return 2

    seeds = _parse_seeds(args.seeds, count=args.count, start=args.seed_start)
    try:
        targets = _targets_for_factory(
            args.factory,
            archetypes=_parse_csv_values(args.archetypes),
            presets=_parse_csv_values(args.presets),
            include_presets=bool(args.include_presets),
        )
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    out_dir = (args.out_dir or (DEFAULT_OUT_ROOT / args.factory)).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / f"{args.factory}_contact_sheet.png"
    manifest_path = out_dir / f"{args.factory}_contact_sheet.json"

    print(
        f"[factory_contact_sheet] factory={args.factory} "
        f"targets={len(targets)} seeds={seeds} out={out_png}"
    )
    cells = _render_cells(
        factory_name=args.factory,
        targets=targets,
        seeds=seeds,
        out_dir=out_dir,
        samples=args.samples,
        size=args.size,
        blender_bin=args.blender,
        timeout=args.timeout,
        refresh=args.refresh,
    )
    _compose_contact_sheet(
        factory_name=args.factory,
        cells=cells,
        out_png=out_png,
        columns=args.columns,
        cell_size=args.cell_size,
    )
    _write_manifest(
        factory_name=args.factory,
        targets=targets,
        seeds=seeds,
        cells=cells,
        out_png=out_png,
        manifest_path=manifest_path,
    )
    failed = [cell for cell in cells if cell.status == "failed"]
    print(f"[factory_contact_sheet] wrote {out_png}")
    print(f"[factory_contact_sheet] wrote {manifest_path}")
    if failed and not args.allow_failures:
        print(f"FAIL: {len(failed)} cell(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
