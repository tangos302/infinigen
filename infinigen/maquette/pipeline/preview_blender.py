"""Inner Blender script for the single-factory preview CLI.

Run via:
    blender --background --python preview_blender.py -- \
        --factory LowPolyPalmTreeFactory \
        --seed 7 \
        --out /tmp/palm.png \
        [--archetype <name>] [--blend /tmp/palm.blend]

Don't invoke this directly — use the user-facing wrapper at
`python -m infinigen.maquette.pipeline.preview`, which handles the
blender subprocess + arg passing + exit-code translation. Living
inside Blender means `bpy` is available; outside Blender this module
is unimportable and that's intentional.

The point of "preview" vs the regular pipeline: validate ONE factory
in isolation with a deterministic seed, in a few seconds, against a
neutral grey ground + 3-light rig. Catches "imports fine but
create_asset crashes / produces nothing" without paying for a full
scene composition.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

# Allow imports from the fork root when blender wasn't launched from there.
INFINIGEN_FORK = Path(__file__).resolve().parent.parent.parent.parent
if str(INFINIGEN_FORK) not in sys.path:
    sys.path.insert(0, str(INFINIGEN_FORK))


# --- factory name → module path --------------------------------------------


def _factory_to_module_stem(factory_name: str) -> str:
    """Same convention as pipeline.implementer: LowPolyPalmTreeFactory →
    palm_tree. Duplicated rather than imported so this file stays runnable
    when bpy import is the first thing blender does (the implementer
    module also imports `shutil.which` and other host-side helpers)."""
    name = factory_name
    if name.startswith("LowPoly"):
        name = name[len("LowPoly") :]
    elif name.startswith("Native"):
        # NativeLowPolyTreeFactory → tree
        name = name[len("Native") :]
        if name.startswith("LowPoly"):
            name = name[len("LowPoly") :]
    if name.endswith("Factory"):
        name = name[: -len("Factory")]
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and not name[i - 1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


_FACTORY_SEARCH_PACKAGES = [
    "infinigen.maquette.factories.native",
    "infinigen.maquette.factories",
    "infinigen.maquette.runtime.loaded_factory",
]


def _load_factory(factory_name: str):
    """Resolve `factory_name` to a class.

    Tries in order:
      1. Package-level import from each search package — works when the
         class is re-exported in __init__.py regardless of which file it
         lives in (e.g. LowPolyHouseFactory comes from native/building.py
         but is exported as `infinigen.maquette.factories.native.LowPolyHouseFactory`).
      2. Submodule import using the convention `LowPolyXFactory → x` —
         catches factories that aren't yet re-exported in __init__.

    Step 1 is the load-bearing path now that the catalog has grown enough
    that submodule names diverge from class names (House lives in building.py,
    Tree lives in tree.py, etc.).
    """
    last_err: Exception | None = None
    for pkg in _FACTORY_SEARCH_PACKAGES:
        try:
            pkg_module = importlib.import_module(pkg)
        except ModuleNotFoundError as exc:
            last_err = exc
            continue
        cls = getattr(pkg_module, factory_name, None)
        if cls is not None:
            return cls

    stem = _factory_to_module_stem(factory_name)
    for pkg in _FACTORY_SEARCH_PACKAGES:
        try:
            module = importlib.import_module(f"{pkg}.{stem}")
        except ModuleNotFoundError as exc:
            last_err = exc
            continue
        cls = getattr(module, factory_name, None)
        if cls is not None:
            return cls
        last_err = AttributeError(
            f"module {pkg}.{stem} has no attribute {factory_name!r}"
        )
    raise RuntimeError(
        f"could not locate {factory_name} (tried package re-exports + "
        f"stem={stem!r}). last error: {last_err}"
    )


# --- scene setup -----------------------------------------------------------


def _wipe_scene() -> None:
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def _add_ground(size: float = 12.0) -> None:
    """Neutral cool-grey square so the asset reads against something. Not
    using a ground material that requires the maquette palette — preview
    should still render even if palette wiring breaks."""
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, 0))
    ground = bpy.context.active_object
    ground.name = "PreviewGround"
    mat = bpy.data.materials.new("PreviewGroundMat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.32, 0.34, 0.36, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.95
    ground.data.materials.append(mat)


def _add_lights() -> None:
    """3-light rig: key SUN warm, fill area cool, rim above. Tuned by eye
    so a 1m cube reads well without blowing out smaller assets."""
    bpy.ops.object.light_add(type="SUN", location=(4, -3, 8))
    sun = bpy.context.active_object
    sun.data.energy = 3.2
    sun.data.color = (1.0, 0.92, 0.78)
    sun.rotation_euler = (math.radians(55), math.radians(18), math.radians(50))

    bpy.ops.object.light_add(type="AREA", location=(-3.5, 2.0, 2.5))
    fill = bpy.context.active_object
    fill.data.energy = 60
    fill.data.color = (0.74, 0.82, 0.96)
    fill.data.size = 4.0

    bpy.ops.object.light_add(type="AREA", location=(0.0, -1.5, 5.5))
    rim = bpy.context.active_object
    rim.data.energy = 140
    rim.data.color = (1.0, 0.98, 0.92)
    rim.data.size = 2.5


def _set_world_bg() -> None:
    """Soft warm-grey background — same gamma as the maquette pipeline so
    a preview render looks consistent with full-scene renders."""
    w = bpy.context.scene.world
    w.use_nodes = True
    w.node_tree.nodes.clear()
    out = w.node_tree.nodes.new("ShaderNodeOutputWorld")
    bg = w.node_tree.nodes.new("ShaderNodeBackground")
    bg.inputs[0].default_value = (0.62, 0.60, 0.58, 1.0)
    bg.inputs[1].default_value = 0.6
    w.node_tree.links.new(bg.outputs[0], out.inputs[0])


def _world_bbox(obj: bpy.types.Object) -> tuple[Vector, Vector]:
    """Aggregate world-space bbox over ``obj`` and its children. Returns
    (min, max). Used to frame the camera tightly around the asset."""
    objs = [obj] + [c for c in obj.children_recursive]
    pts: list[Vector] = []
    for o in objs:
        if o.type != "MESH" and not o.children:
            continue
        for v in o.bound_box:
            pts.append(o.matrix_world @ Vector(v))
    if not pts:
        return Vector((-0.5, -0.5, 0)), Vector((0.5, 0.5, 1))
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return mn, mx


def _asset_stats(obj: bpy.types.Object) -> dict:
    """Return cheap QA stats for an asset preview."""
    objs = [obj] + [c for c in obj.children_recursive]
    mesh_objs = [o for o in objs if o.type == "MESH" and getattr(o, "data", None) is not None]
    polygons = sum(len(o.data.polygons) for o in mesh_objs)
    vertices = sum(len(o.data.vertices) for o in mesh_objs)
    mn, mx = _world_bbox(obj)
    size = mx - mn
    return {
        "object_count": len(objs),
        "mesh_object_count": len(mesh_objs),
        "polygons": int(polygons),
        "vertices": int(vertices),
        "bbox_min": [round(float(mn.x), 4), round(float(mn.y), 4), round(float(mn.z), 4)],
        "bbox_max": [round(float(mx.x), 4), round(float(mx.y), 4), round(float(mx.z), 4)],
        "bbox_size": [round(float(size.x), 4), round(float(size.y), 4), round(float(size.z), 4)],
    }


def _frame_camera(target: bpy.types.Object) -> None:
    """Place the camera at a 30° elevation, 35° azimuth, distance scaled
    to the asset's bbox so small props don't appear as dust specks and
    large buildings aren't off-canvas."""
    mn, mx = _world_bbox(target)
    center = (mn + mx) * 0.5
    size = mx - mn
    radius = max(size.x, size.y, size.z, 1.0)
    # Diagonal frame factor — 2.2 leaves a bit of headroom on either side
    # and matches the look of the full-scene renders well enough that
    # preview thumbnails can sit next to scene renders without feeling off.
    dist = radius * 2.2 + 1.0

    az = math.radians(35)
    el = math.radians(30)
    cam_loc = Vector((
        center.x + dist * math.cos(el) * math.sin(az),
        center.y - dist * math.cos(el) * math.cos(az),
        center.z + dist * math.sin(el) + size.z * 0.15,
    ))
    bpy.ops.object.camera_add(location=cam_loc)
    cam = bpy.context.active_object
    # Aim at the asset center; track-to constraint is overkill for one frame.
    direction = (center - cam_loc).normalized()
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = 50
    bpy.context.scene.camera = cam


def _render(out_png: Path, *, samples: int = 32, w: int = 720, h: int = 720) -> None:
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = samples
    sc.render.resolution_x = w
    sc.render.resolution_y = h
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.render.filepath = str(out_png)
    bpy.ops.render.render(write_still=True)


# --- entry point -----------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    """Args after the `--` separator that blender passes through to the
    script. Blender consumes everything before it for its own flags."""
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(prog="preview_blender")
    parser.add_argument("--factory", required=True,
                        help="Factory class name, e.g. LowPolyPalmTreeFactory")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--archetype", default=None,
                        help="Optional archetype kwarg. The kwarg name is "
                             "auto-detected from the factory __init__ params.")
    parser.add_argument("--preset", default=None,
                        help="Named preset from infinigen.maquette.factory_presets. "
                             "Mutually exclusive with --archetype "
                             "(presets bundle their own archetype).")
    parser.add_argument("--out", required=True, help="PNG output path")
    parser.add_argument("--blend", default=None,
                        help="Optional .blend save path (handy for debugging "
                             "a factory that renders empty)")
    parser.add_argument("--metadata", default=None,
                        help="Optional JSON metadata output path")
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--size", type=int, default=720)
    return parser.parse_args(argv)


def _archetype_kwarg_name(factory_cls) -> str | None:
    """Find the `*_archetype` param name in the factory __init__ so the
    caller can pass `--archetype foo` without knowing whether it's
    `building_archetype` or `barrel_archetype` etc."""
    import inspect

    sig = inspect.signature(factory_cls.__init__)
    if "archetype" in sig.parameters:
        return "archetype"
    for name in sig.parameters:
        if name.endswith("_archetype"):
            return name
    return None


def main() -> int:
    args = _parse_args()

    cls = _load_factory(args.factory)

    if args.preset and args.archetype:
        print("FAIL: --preset and --archetype are mutually exclusive "
              "(presets carry their own archetype)", file=sys.stderr)
        return 2

    kwargs: dict
    if args.preset is not None:
        # Defer the import so a typo in the factory_presets module doesn't
        # blow up renders that don't use presets.
        from infinigen.maquette.factory_presets import get_preset
        try:
            kwargs = get_preset(args.factory, args.preset)
        except KeyError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 2
        kwargs["factory_seed"] = args.seed
    else:
        kwargs = {"factory_seed": args.seed}
        if args.archetype is not None:
            ak = _archetype_kwarg_name(cls)
            if ak is None:
                print(f"WARN: factory {args.factory} has no *_archetype param; "
                      f"--archetype ignored", file=sys.stderr)
            else:
                kwargs[ak] = args.archetype

    _wipe_scene()
    _add_ground()
    _set_world_bg()
    _add_lights()

    factory = cls(**kwargs)
    if hasattr(factory, "spawn_asset") and not hasattr(factory, "create_asset"):
        asset = factory.spawn_asset(i=0, loc=(0, 0, 0))
        if asset is None:
            print(f"FAIL: {args.factory}.spawn_asset returned None", file=sys.stderr)
            return 2
        stats = _asset_stats(asset)
        _frame_camera(asset)

        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _render(out_path, samples=args.samples, w=args.size, h=args.size)

        if args.blend:
            blend_path = Path(args.blend)
            blend_path.parent.mkdir(parents=True, exist_ok=True)
            bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

        if args.metadata:
            metadata_path = Path(args.metadata)
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            metadata = {
                "factory": args.factory,
                "seed": int(args.seed),
                "archetype": args.archetype,
                "preset": args.preset,
                "output": str(out_path),
                "stats": stats,
            }
            metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")

        print(f"OK: {out_path}")
        return 0

    # `create_asset` signatures diverge across the catalog:
    #   - Native factories: `create_asset(self, placeholder=None, **kw)`
    #   - Upstream wrappers (BoulderFactory etc.): `create_asset(self, i,
    #     placeholder, face_size=..., ...)` — require a real placeholder
    #     to derive bbox + an instance index `i`.
    # Sniff the signature so the preview works for both.
    import inspect
    ca_params = inspect.signature(cls.create_asset).parameters
    needs_i = "i" in ca_params and ca_params["i"].default is inspect.Parameter.empty
    placeholder = factory.create_placeholder(i=0) if "i" in inspect.signature(cls.create_placeholder).parameters else factory.create_placeholder()
    # Some wrappers expect the placeholder to have a meaningful bbox /
    # location; give it a default scale so downstream bbox-derived math
    # doesn't divide by zero.
    if placeholder is not None and hasattr(placeholder, "scale"):
        try:
            placeholder.scale = (1.5, 1.5, 1.5)
        except Exception:
            pass
    call_kwargs: dict = {"placeholder": placeholder}
    if needs_i:
        call_kwargs["i"] = 0
    try:
        asset = factory.create_asset(**call_kwargs)
    except TypeError as exc:
        # Last-ditch — try the native convention.
        try:
            asset = factory.create_asset(placeholder=None)
        except Exception:
            print(f"FAIL: {args.factory}.create_asset({call_kwargs.keys()}) -> {exc}",
                  file=sys.stderr)
            return 2
    if asset is None:
        print(f"FAIL: {args.factory}.create_asset returned None", file=sys.stderr)
        return 2

    stats = _asset_stats(asset)
    _frame_camera(asset)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _render(out_path, samples=args.samples, w=args.size, h=args.size)

    if args.blend:
        blend_path = Path(args.blend)
        blend_path.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    if args.metadata:
        metadata_path = Path(args.metadata)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {
            "factory": args.factory,
            "seed": int(args.seed),
            "archetype": args.archetype,
            "preset": args.preset,
            "output": str(out_path),
            "stats": stats,
        }
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")

    print(f"OK: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
