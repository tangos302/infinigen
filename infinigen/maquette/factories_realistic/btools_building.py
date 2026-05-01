"""RealisticBToolsBuildingFactory — parametric building, wraps building_tools.

Source: ranjian0/building_tools (GPL-3, https://github.com/ranjian0/building_tools).
Installed under `~/.config/blender/4.2/scripts/addons/building_tools/`.
We patch two upstream issues to make it headless-friendly (see
project_realistic_mode.md).

Programmatic API: floorplan → floors → roof. Each step requires the
mesh to be in EDIT mode with the right faces selected:

  - floors: all faces (or top edge ring) selected
  - roof:   only top-facing faces (normal.z > 0) selected — upstream's
            validate_roof_faces() rejects the call otherwise

We handle the EDIT-mode dance + selection internally so callers see a
clean spawn_asset() interface.

Archetype mapping → (floorplan size, storey count, storey height,
roof type, roof height):

    "cottage"     : 4×4m × 1 storey × 2.5m, hip roof 1.2m
    "two_storey"  : 6×4m × 2 × 2.5m, hip roof 1.5m
    "barn"        : 8×5m × 1 × 3.5m, gable roof 2.5m
    "tower"       : 3×3m × 4 × 2.5m, hip roof 1.0m (steep)
    "longhouse"   : 12×4m × 1 × 3.0m, gable roof 2.0m (long ridge)
    "any"         : random pick

License: GPL-3 (Building Tools is GPL-3; this wrapper inherits).
"""

from __future__ import annotations

import logging

import bpy
import numpy as np

from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util.math import FixedSeed

logger = logging.getLogger(__name__)

_BUILDING_ARCHETYPES = (
    "cottage", "two_storey", "barn", "tower", "longhouse", "any",
)

# (width, length, floor_count, floor_height, roof_type, roof_height)
# roof_type matches building_tools' RoofType enum: "HIP" | "GABLE" | "FLAT".
_ARCHETYPE_PRESETS: dict[str, tuple[float, float, int, float, str, float]] = {
    "cottage":    (4.0, 4.0, 1, 2.5, "HIP",   1.2),
    "two_storey": (6.0, 4.0, 2, 2.5, "HIP",   1.5),
    "barn":       (8.0, 5.0, 1, 3.5, "GABLE", 2.5),
    "tower":      (3.0, 3.0, 4, 2.5, "HIP",   1.0),
    "longhouse":  (12.0, 4.0, 1, 3.0, "GABLE", 2.0),
}


def _make_pbr_material(name: str, base_color, roughness: float = 0.7) -> bpy.types.Material:
    """Build a tiny Principled-BSDF material with the given diffuse + roughness.

    We only need three of these (wall, roof, foundation) per scene, and
    Cycles dedups by node tree, so creating fresh ones per spawn is cheap.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
    return mat


def _apply_building_materials(obj, archetype: str) -> None:
    """Attach a 3-slot material set (wall / roof / foundation).

    Building Tools tracks face → group via two pieces of data:
      - `obj.data.attributes['.bt_material_group_index']` holds a
        per-face int index.
      - `obj.bt_materials` is a CollectionProperty whose entries have
        a ``.name`` (lowercased MaterialGroup label) at each index.

    We read both, then map each face's group name to one of three
    PBR materials (wall / roof / foundation slab).
    """
    me = obj.data
    mat_attr = me.attributes.get(".bt_material_group_index")
    if mat_attr is None or mat_attr.domain != "FACE":
        return  # No grouping data — leave default.

    bt_mats = getattr(obj, "bt_materials", None)
    if bt_mats is None:
        return

    # Build index → group_name lookup from the bt_materials collection.
    group_name_by_index: dict[int, str] = {}
    for entry in bt_mats:
        group_name_by_index[int(entry.index)] = str(entry.name).lower()

    # Tone palette per archetype — earthy stone, muted wood, slate.
    if archetype in ("barn", "longhouse"):
        wall_color = (0.50, 0.36, 0.24)   # dark wood
        roof_color = (0.40, 0.28, 0.18)   # weathered shingle
        slab_color = (0.45, 0.42, 0.38)   # stone foundation
    elif archetype == "tower":
        wall_color = (0.62, 0.60, 0.55)   # pale stone
        roof_color = (0.30, 0.32, 0.36)   # slate
        slab_color = (0.45, 0.42, 0.38)
    else:  # cottage / two_storey
        wall_color = (0.78, 0.72, 0.62)   # stucco / plaster
        roof_color = (0.45, 0.30, 0.24)   # terracotta
        slab_color = (0.45, 0.42, 0.38)

    me.materials.clear()
    me.materials.append(_make_pbr_material("BuildingWall", wall_color, 0.75))
    me.materials.append(_make_pbr_material("BuildingRoof", roof_color, 0.55))
    me.materials.append(_make_pbr_material("BuildingSlab", slab_color, 0.85))

    def slot_for(name: str) -> int:
        if "roof" in name:
            return 1
        if "slab" in name:
            return 2
        return 0

    n_polys = len(me.polygons)
    if len(mat_attr.data) != n_polys:
        return
    for poly_idx, item in enumerate(mat_attr.data):
        try:
            group_idx = int(item.value)
        except AttributeError:
            continue
        group_name = group_name_by_index.get(group_idx, "")
        me.polygons[poly_idx].material_index = slot_for(group_name)


def _ensure_btools_loaded():
    """Enable the building_tools addon and import its API.

    Returns the api module. Cached after first call so repeated
    spawn_asset() calls don't re-register.
    """
    global _btools_api
    try:
        return _btools_api  # type: ignore[name-defined]
    except NameError:
        pass

    import sys
    addon_dir = "/home/tang/.config/blender/4.2/scripts/addons"
    if addon_dir not in sys.path:
        sys.path.insert(0, addon_dir)

    import addon_utils
    if not addon_utils.check("building_tools")[1]:
        addon_utils.enable("building_tools", default_set=False)

    from building_tools.btools import api as _api
    _btools_api = _api
    return _btools_api


class RealisticBToolsBuildingFactory(AssetFactory):
    """Realistic procedural building factory (Building Tools wrapper).

    Constructor knobs:

        factory_seed : int
        archetype : str = "two_storey"
            One of: cottage / two_storey / barn / tower / longhouse / any.
        slab : bool = True  (whether to include a foundation slab)
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "two_storey",
        slab: bool = True,
        coarse: bool = False,
    ):
        if archetype not in _BUILDING_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_BUILDING_ARCHETYPES}"
            )
        super().__init__(factory_seed, coarse=coarse)
        if archetype == "any":
            with FixedSeed(factory_seed):
                non_any = list(_ARCHETYPE_PRESETS.keys())
                archetype = str(np.random.choice(non_any))
        self.archetype = archetype
        self.slab = slab

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        empty = bpy.data.objects.new("BuildingPlaceholder", None)
        bpy.context.collection.objects.link(empty)
        return empty

    def create_asset(self, i: int = 0, placeholder=None, **params) -> bpy.types.Object:
        import bmesh
        api = _ensure_btools_loaded()
        width, length, floor_count, floor_height, roof_type, roof_height = (
            _ARCHETYPE_PRESETS[self.archetype]
        )

        # 1. Create floorplan (a flat polygon) — leaves it as the active object.
        api.create_floorplan(
            api.FloorplanOptions(width=width, length=length)
        )
        building = bpy.context.object

        # 2. Enter EDIT mode + select all faces for floor extrusion.
        try:
            bpy.ops.object.select_all(action="DESELECT")
        except RuntimeError:
            pass
        building.select_set(True)
        bpy.context.view_layer.objects.active = building
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")

        # 3. Extrude floors.
        api.create_floors(api.FloorOptions(
            floor_count=floor_count,
            floor_height=floor_height,
            add_slab=self.slab,
        ))

        # 4. Door + windows. BTools needs ONE wall face selected per
        # call. Walls have |normal.z| < 0.3; we pick faces by Z-band so
        # door lands ground-level, windows land mid-storey.
        me = building.data
        bm = bmesh.from_edit_mesh(me)

        def _select_first_wall_in_band(z_low: float, z_high: float) -> bool:
            for f in bm.faces:
                f.select = False
            for f in bm.faces:
                if abs(f.normal.z) > 0.3:
                    continue
                center_z = sum(v.co.z for v in f.verts) / len(f.verts)
                if z_low <= center_z <= z_high:
                    f.select = True
                    bmesh.update_edit_mesh(me)
                    return True
            bmesh.update_edit_mesh(me)
            return False

        # Door at ground level.
        if _select_first_wall_in_band(0.5, 1.5):
            try:
                api.create_door(api.DoorOptions(
                    frame_thickness=0.08, frame_depth=0.05, door_depth=0.04,
                ))
                bm = bmesh.from_edit_mesh(me)  # bm reference may be stale
            except Exception:
                pass

        # One window per storey at the storey's mid-height.
        for storey in range(floor_count):
            mid_z = storey * floor_height + floor_height * 0.55
            if _select_first_wall_in_band(mid_z - 0.25, mid_z + 0.25):
                try:
                    api.create_window(api.WindowOptions(
                        frame_thickness=0.06, frame_depth=0.04,
                    ))
                    bm = bmesh.from_edit_mesh(me)
                except Exception:
                    pass

        # 5. Re-select top-facing faces for roof. Walls have normal.z ≈ 0;
        # roof validator only accepts faces with non-zero z normal.
        bm = bmesh.from_edit_mesh(me)
        for f in bm.faces:
            f.select = False
        max_z = max((v.co.z for v in bm.verts), default=0.0)
        for f in bm.faces:
            if f.normal.z > 0.5 and any(v.co.z > max_z - 0.01 for v in f.verts):
                f.select = True
        bmesh.update_edit_mesh(me)

        # 6. Roof.
        api.create_roof(api.RoofOptions(
            type=api.RoofType[roof_type],
            height=roof_height,
            thickness=0.1,
            outset=0.15,
        ))

        bpy.ops.object.mode_set(mode="OBJECT")
        building.name = f"Building.{self.archetype}.{i}"

        # 7. Apply materials based on Building Tools' bt_material_group
        # face attribute — wall vs roof vs slab get distinct PBR colours.
        _apply_building_materials(building, self.archetype)

        return building
