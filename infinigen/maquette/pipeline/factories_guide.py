"""Auto-generate FACTORIES_GUIDE.md from the factory module ASTs.

Walks `infinigen/maquette/factories/{*.py, native/*.py}`, extracts:
  - module docstring (sales pitch — what the factory is for)
  - `_<X>_ARCHETYPES` tuple (the list of archetype names)
  - `_ARCHETYPE_DEFAULTS` dict (default knob values per archetype —
    not exhaustively dumped, just shape-summarized for tokens)
  - class docstring's "Constructor knobs" section (parameter list)

Output is a markdown doc that goes to Claude as the catalog. Claude
then writes a build script that calls the factories.

Why AST instead of import: importing the modules pulls in `bpy` which
needs Blender. The pipeline runs from a regular Python env (not inside
Blender), so we keep the guide-gen Blender-free.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path


FORK_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # infinigen-fork/
MAQUETTE_DIR = FORK_ROOT / "infinigen" / "maquette"
FACTORIES_DIR = MAQUETTE_DIR / "factories"


# High-level category for each factory module — used by the /debug/factories
# page to group the catalog into something a designer can scan. Keys are
# module stems (file names without .py); modules not listed default to
# "objects" so a new factory shows up without needing edits here.
FACTORY_CATEGORIES: dict[str, str] = {
    # terrain — vegetation, rock features, things rooted in the ground
    "tree": "terrain",
    "palm_tree": "terrain",
    "cactus": "terrain",
    "rock_spire": "terrain",
    "boulder": "terrain",
    "tumbleweed": "terrain",
    # water — anything water-bound
    "water_surface": "water",
    "boat": "water",
    # objects — small props, scatter, ground furniture
    "barrel": "objects",
    "crate": "objects",
    "fence": "objects",
    "haystack": "objects",
    "lantern_post": "objects",
    "banner": "objects",
    "stall": "objects",
    "wagon": "objects",
    "deck": "objects",
    # landmark — large structures, focal points, civilisation
    "building": "landmark",
    "suspension_bridge": "landmark",
    "cable_car": "landmark",
    "torii": "landmark",
    "well": "landmark",
    "windmill": "landmark",
    "tombstone": "landmark",
}

CATEGORY_ORDER: list[str] = ["terrain", "water", "landmark", "objects"]


def category_for(module_stem: str) -> str:
    """Return the high-level category for a factory module. Falls back to
    'objects' for unmapped modules so new factories show up automatically."""
    return FACTORY_CATEGORIES.get(module_stem, "objects")


def _module_docstring(tree: ast.Module) -> str | None:
    """First-statement string literal at the module level."""
    return ast.get_docstring(tree)


def _find_archetype_tuples(tree: ast.Module) -> list[tuple[str, list[str]]]:
    """Find all module-level `_<NAME>_ARCHETYPES = (...)` assignments.
    Returns [(name, values), ...] in source order. Some factories have
    multiple archetype tuples (e.g. building.py has `_BUILDING_ARCHETYPES`
    and `_ROOF_ARCHETYPES`)."""
    out = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id.endswith("_ARCHETYPES"):
                if isinstance(node.value, (ast.Tuple, ast.List)):
                    values = []
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            values.append(elt.value)
                    out.append((tgt.id, values))
    return out


def _find_class_init(tree: ast.Module, class_name: str) -> ast.FunctionDef | None:
    """Find the __init__ method of the given class."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == "__init__":
                    return sub
    return None


def _format_init_params(init_fn: ast.FunctionDef) -> list[str]:
    """Authoritative parameter list, formatted as a markdown bullet list.
    Skips `self` and `coarse` (always present, never useful to scene
    builders)."""
    args = init_fn.args
    all_args = list(args.args)  # positional + keyword-only collapse
    # Defaults align with the *trailing* args; len(defaults) <= len(args)
    defaults = list(args.defaults)
    n_args = len(all_args)
    n_def = len(defaults)
    # Pad defaults so each arg has a default (None if none).
    padded = [None] * (n_args - n_def) + defaults
    out = []
    for arg, default in zip(all_args, padded):
        if arg.arg in ("self", "coarse"):
            continue
        annotation = ""
        if arg.annotation is not None:
            try:
                annotation = ": " + ast.unparse(arg.annotation)
            except Exception:
                annotation = ""
        default_str = ""
        if default is not None:
            try:
                default_str = " = " + ast.unparse(default)
            except Exception:
                default_str = ""
        out.append(f"{arg.arg}{annotation}{default_str}")
    return out


def _find_archetype_defaults_keys(tree: ast.Module) -> list[str]:
    """Return the keys of the `_ARCHETYPE_DEFAULTS` dict's first archetype
    entry — that is, the list of knobs each archetype defaults dict
    declares. Used to surface the per-archetype knob set without dumping
    the full dict to the guide."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id == "_ARCHETYPE_DEFAULTS":
                if isinstance(node.value, ast.Dict):
                    if not node.value.values:
                        return []
                    first_val = node.value.values[0]
                    if isinstance(first_val, ast.Call):
                        return [k.arg for k in first_val.keywords if k.arg]
                    if isinstance(first_val, ast.Dict):
                        return [
                            k.value for k in first_val.keys
                            if isinstance(k, ast.Constant) and isinstance(k.value, str)
                        ]
    return []


def _find_factory_class(tree: ast.Module) -> tuple[str, str] | None:
    """Return (class_name, docstring) for the first class that subclasses
    AssetFactory."""
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            base_name = (
                base.attr if isinstance(base, ast.Attribute)
                else base.id if isinstance(base, ast.Name)
                else None
            )
            if base_name == "AssetFactory":
                return node.name, ast.get_docstring(node) or ""
    return None


def _factory_files() -> list[Path]:
    """All *.py files in factories/ and factories/native/ except __init__."""
    out = []
    for p in sorted(FACTORIES_DIR.glob("*.py")):
        if p.stem != "__init__":
            out.append(p)
    for p in sorted((FACTORIES_DIR / "native").glob("*.py")):
        if p.stem != "__init__":
            out.append(p)
    return out


def _entry_for(path: Path) -> str | None:
    """Build the markdown entry for a single factory file."""
    src = path.read_text()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    cls = _find_factory_class(tree)
    if cls is None:
        return None
    class_name, _class_doc = cls
    mod_doc = _module_docstring(tree) or ""
    # First non-empty line of module doc as one-line pitch
    mod_pitch = next((ln for ln in mod_doc.splitlines() if ln.strip()), "")
    archetype_tuples = _find_archetype_tuples(tree)
    init_fn = _find_class_init(tree, class_name)

    parts = [f"### `{class_name}`", ""]
    if mod_pitch:
        parts.append(mod_pitch.strip())
        parts.append("")
    for name, values in archetype_tuples:
        # Strip the leading `_` and trailing `_ARCHETYPES` for readability:
        # `_BUILDING_ARCHETYPES` → `building`
        label = name.strip("_").removesuffix("_ARCHETYPES").lower() or "archetype"
        parts.append(f"**{label}** archetypes: `{'` / `'.join(values)}`")
    if archetype_tuples:
        parts.append("")
    if init_fn is not None:
        params = _format_init_params(init_fn)
        if params:
            parts.append("**Constructor parameters:**")
            parts.append("```")
            for p in params:
                parts.append(p)
            parts.append("```")
    parts.append("")
    return "\n".join(parts)


_HEADER = """\
# Maquette Factory Catalog (auto-generated)

This is the procedural-asset catalog for low-poly stylized scene
generation. Each factory below produces ONE class of asset (tree,
boulder, building, etc.) with multiple archetypes selectable via a
`*_archetype` constructor parameter.

## Conventions for build scripts

Every build script you generate MUST follow this skeleton:

```python
import sys, math, random
from pathlib import Path
INFINIGEN_FORK = Path("/home/tang/songe/_artifacts/maquette/infinigen-fork")
if str(INFINIGEN_FORK) not in sys.path:
    sys.path.insert(0, str(INFINIGEN_FORK))

import bpy
from mathutils import Vector

from infinigen.maquette.factories.native.<module> import LowPoly<X>Factory
# ... repeat for each factory you need
from infinigen.maquette.factories.boulder import LowPolyBoulderFactory  # wrapper
from infinigen.maquette.runtime.terrain import make_terrain
# OR — when the prompt mixes biomes (grass + desert, forest + coast, etc.):
# from infinigen.maquette.runtime.terrain import make_multi_biome_terrain
# OR — for SERIOUS terrain (dramatic peaks + river systems + image refs):
# from infinigen.maquette.runtime.eroded_terrain import make_eroded_terrain

rng = random.Random(<seed>)

# 1. Wipe scene + create displaced ground. NEVER build it as a bare plane.
# Pick the helper that fits the prompt:
#   make_terrain(style=...)             — flat/rolling/hilly/alpine/dunes,
#                                         single biome, fast.
#   make_multi_biome_terrain(zones=...) — mixed biomes side-by-side,
#                                         simple zone blender (faceted edges).
#   make_eroded_terrain(peaks=, troughs=) — game-ready quality.
#                                         Hydraulic erosion (landlab) +
#                                         continuous biome colors.
#                                         REQUIRED when the prompt names
#                                         dramatic terrain (mountain ranges,
#                                         river valleys, "vast plains with
#                                         a peak in the distance"), or any
#                                         time an image reference is provided
#                                         showing complex relief.
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
terrain = make_terrain(
    style="<flat|rolling|hilly|alpine|dunes>",
    size=80,                                # half-width in BU; world 160 BU wide
    base_color=(<R>, <G>, <B>, 1.0),
    seed=<scene seed>,
)
# Multi-biome alternative (replace the single-biome call above when needed):
#   terrain = make_multi_biome_terrain(
#       size=80,
#       seed=<seed>,
#       zones=[
#           ("rolling", -30,   0, 25),   # grass headland on the west
#           ("dunes",    20,  -8, 22),   # sandy fringe on the southeast
#           ("flat",      0,  38, 30),   # ocean side (add water plane on top)
#       ],
#   )
# Eroded (game-ready) alternative — peaks + troughs spec:
#   terrain = make_eroded_terrain(
#       size=140,                         # bigger world; relief reads at 280 BU wide
#       seed=<seed>,
#       peaks=[
#           # (cx, cy, sigma, height) — Gaussians for mountain masses.
#           # Heights ≥12 BU get ridged-noise alpine character + snow caps.
#           (115, 50, 25, 18.0),          # hero alpine NE
#           (-110, 70, 18, 4.5),          # secondary western range
#           (-95, -110, 22, 5.0),         # foreground vantage hill (camera vp)
#       ],
#       troughs=[
#           # (cx, cy, sigma, depth NEGATIVE) — chain these to thread a
#           # winding river/lake basin. Erosion will carve drainage from peaks
#           # toward the troughs naturally.
#           (-40, -10, 14, -3.6),
#           ( 5,   5, 12, -3.4),
#           ( 30, 20, 14, -3.2),
#       ],
#       plain_offset=2.4,                  # lift plains so meadow dominates
#       sea_level=0.5,                     # below = lakebed/shore
#       erode_iters=35,                    # 25 soft, 35 default, 60 aggressive
#       # water=True is the default — auto-detects connected basins
#       # below sea_level and drops one translucent blue cube per body.
#       # Pass water=False to suppress (terrain-only renders).
#   )
# After this call: `terrain.height_at(x, y)` returns the eroded surface
# height at any world XY — use it the same way as make_terrain.
# DO NOT add LowPolyWaterSurfaceFactory on top of make_eroded_terrain —
# the helper already places water volumes per basin from the heightmap.

# 2. Spawn assets via factories.
#    Pattern: f = FactoryClass(factory_seed=N, archetype="...")
#             obj = f.create_asset(placeholder=None)
#             obj.location = (x, y, terrain.height_at(x, y))   # ride the surface
#             obj.rotation_euler.z = rot_z
#
#    LowPolyBoulderFactory needs spawn_asset (Infinigen wrapper):
#             obj = f.spawn_asset(i=N, loc=(x, y, terrain.height_at(x, y)))
#
#    For water surfaces, sit them slightly below local terrain height
#    so they read as a valley channel:
#             lake_z = terrain.height_at(cx, cy) - 0.3

# 3. Camera + sun + world background
bpy.ops.object.camera_add(location=(<X>, <Y>, <Z>))
cam = bpy.context.active_object
target = Vector((<tx>, <ty>, <tz>))
cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
cam.data.lens = 35
bpy.context.scene.camera = cam

bpy.ops.object.light_add(type="SUN", location=(<X>, <Y>, <Z>))
sun = bpy.context.active_object
sun.data.energy = <energy>            # 2.0 daytime, 2.5 golden, 1.4 twilight, 3.5 harsh
sun.data.color = (<R>, <G>, <B>)      # warm: 1,0.86,0.65; neutral: 1,0.96,0.88; cool: 0.65,0.62,0.78
sun.rotation_euler = (math.radians(<pitch>), math.radians(<roll>), math.radians(<yaw>))

w = bpy.context.scene.world
w.use_nodes = True
w.node_tree.nodes.clear()
out = w.node_tree.nodes.new("ShaderNodeOutputWorld")
bg = w.node_tree.nodes.new("ShaderNodeBackground")
bg.inputs[0].default_value = (<R>, <G>, <B>, 1.0)
bg.inputs[1].default_value = 1.0
w.node_tree.links.new(bg.outputs[0], out.inputs[0])

# 4. Render + save (the pipeline expects these exact paths)
import os
OUT_DIR = Path(os.environ["MAQUETTE_OUT_DIR"])
sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.samples = 48
sc.render.resolution_x = 1920
sc.render.resolution_y = 1080
sc.render.resolution_percentage = 100
sc.view_settings.view_transform = "Standard"
sc.render.filepath = str(OUT_DIR / "scene.png")
sc.render.image_settings.file_format = "PNG"
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT_DIR / "scene.blend"))
print(f"DONE: {OUT_DIR}/scene.png")
```

### Layout patterns

Use these archetypal patterns rather than reinventing — they read well
at low poly:

  - **Forest ring**: scatter ~15-25 trees in a circle of radius 15-22m
    around the central scene; randomize archetype + scale 0.85-1.2.
  - **Building cluster**: 3-5 houses arranged around a central focal
    point (well, square, plaza), each rotated to face inward.
  - **Path props**: lanterns or torii at regular intervals along the
    travel direction.
  - **Riprap**: scatter 5-10 boulders along the water/wall edge for
    natural transition.
  - **Yard scatter**: barrels + crates in clusters of 3-5 next to
    building doors.

### Material slots

Every factory uses `apply_palette_slots` so caller can override colours
per slot. Most factories have 2-3 slots (body, accent, trim). To pick a
non-default colour, pass `<slot>_color="palette_key"` to the factory.

Available palette keys:
`rock_warm`, `rock_cool`, `rock_pale`, `rock_shadow`, `wood`,
`rust_metal`, `stucco`, `foliage_pine`, `foliage_bush`, `foliage_apple`,
`foliage_mint`, `foliage_amber`, `foliage_rose`, `foliage_amethyst`,
`foliage_lemon`, `foliage_coral`, `ground_sand`, `ground_grass`,
`water`, `sky_warm`, `sky_cool`, `accent_red`.

### Lighting recipes (golden-hour palette baked in)

  - **Daytime / overcast**: sun energy 2.0, color `(1.0, 0.96, 0.88)`,
    rotation `(45°, 15°, 70°)`, sky `(0.78, 0.82, 0.88, 1.0)`
  - **Golden hour / sunset**: energy 2.5, color `(1.0, 0.86, 0.65)`,
    rotation `(60°, 20°, 60°)`, sky `(0.86, 0.78, 0.62, 1.0)`
  - **Dawn**: energy 2.5, color `(1.0, 0.78, 0.55)`,
    rotation `(75°, 15°, 45°)`, sky `(0.78, 0.65, 0.62, 1.0)`
  - **Twilight**: energy 1.4, color `(0.65, 0.62, 0.78)`,
    rotation `(80°, 15°, 120°)`, sky `(0.40, 0.42, 0.55, 1.0)`
  - **Wasteland midday**: energy 3.5, color `(1.0, 0.92, 0.78)`,
    rotation `(80°, 0°, 15°)`, sky `(0.92, 0.78, 0.62, 1.0)`

### Missing factories

If a prompt needs an asset class that's not in the catalog below,
include a comment in the script of the form:

```python
# REQUESTED_ASSET: <FactoryName> — <what it should be>
```

Use the closest existing factory as a stand-in (e.g. crystal-foliage
trees for dead trees, stone_wall fence for tombstones if Tombstone is
missing) and CONTINUE building the scene. Do not refuse to build.

### Camera framing

Use `cam.data.lens = 35` for wide scene shots and `lens = 50` for tight
prop shots. For an oblique-aerial scene view of a size=80 (160 BU wide)
world, the camera at `(40, -44, 26)` looking at `(0, 0, 3)` frames the
full scene cleanly. Scale linearly with terrain size if you change it.

---

## Factories

"""


_FOOTER = """\

---

Generated automatically by `infinigen.maquette.pipeline.factories_guide`.
"""


def build_guide() -> str:
    """Build the full markdown guide string."""
    parts = [_HEADER]
    for path in _factory_files():
        entry = _entry_for(path)
        if entry:
            parts.append(entry)
    parts.append(_FOOTER)
    return "\n".join(parts)


def write_guide(out_path: Path | None = None) -> Path:
    """Build and write to disk. Default location: infinigen/maquette/FACTORIES_GUIDE.md."""
    if out_path is None:
        out_path = MAQUETTE_DIR / "FACTORIES_GUIDE.md"
    out_path.write_text(build_guide())
    return out_path


def _structured_entry_for(path: Path) -> dict | None:
    """Return a dict describing a single factory module, or None if the
    file isn't a factory. Used by the debug API to render the catalog as
    structured data instead of free-form markdown."""
    src = path.read_text()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    cls = _find_factory_class(tree)
    if cls is None:
        return None
    class_name, class_doc = cls
    mod_doc = _module_docstring(tree) or ""
    archetype_tuples = _find_archetype_tuples(tree)
    init_fn = _find_class_init(tree, class_name)
    params = _format_init_params(init_fn) if init_fn is not None else []
    rel_path = path.relative_to(FORK_ROOT)
    return {
        "module": path.stem,
        "module_path": str(rel_path),
        "class_name": class_name,
        "category": category_for(path.stem),
        "module_doc": mod_doc.strip(),
        "class_doc": (class_doc or "").strip(),
        "archetypes": [
            {"label": name.strip("_").removesuffix("_ARCHETYPES").lower() or "archetype",
             "values": values}
            for name, values in archetype_tuples
        ],
        "constructor_params": params,
        "default_knobs": _find_archetype_defaults_keys(tree),
    }


def list_factories() -> list[dict]:
    """Return a structured list of every factory in the catalog."""
    out: list[dict] = []
    for path in _factory_files():
        entry = _structured_entry_for(path)
        if entry is not None:
            out.append(entry)
    return out


if __name__ == "__main__":
    p = write_guide()
    print(f"Wrote {p} ({p.stat().st_size:,} bytes)")
