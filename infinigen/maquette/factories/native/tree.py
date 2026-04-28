"""NativeLowPolyTreeFactory — Sapling-derived native low-poly tree.

Reproduces the core of Blender's Sapling Tree Gen / MTree algorithm:
  1. Generate a SKELETON as a list of (parent_idx, position, radius)
     tuples. Trunk + branches as a tree-shaped graph.
  2. Apply Blender's SKIN modifier to the skeleton to produce a
     tube mesh — this handles perpendicular-frame transport along
     curves automatically, the way Sapling does.
  3. Add a STACKED-ICOSPHERE foliage clump at the top (Firewatch-style
     deformed-balloon foliage — single mesh, NOT instanced leaves).
  4. Flat-shade and apply a Maquette palette color.

Why this is structurally different from Maquette's `LowPolyTreeFactory`
(which wraps Infinigen's TreeFactory):
  - Infinigen's foliage is a leaf-collection instanced via geometry
    nodes — incompatible with single-mesh balloon foliage.
  - Infinigen's branch skin produces 100k+ polys we then decimate
    down. Going low-poly first is faster and gives cleaner topology.
  - Sapling's per-level params (length, radius, branch count, angle,
    curvature) translate directly to a few constructor knobs here.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import bmesh
import bpy
import numpy as np
from mathutils import Quaternion, Vector

from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util import blender as butil

from ...materials import apply_palette, apply_palette_slots


# ---------------------------------------------------------------------------
# Skeleton — pure-data, no Blender API
# ---------------------------------------------------------------------------


@dataclass
class _SkeletonNode:
    """One node in the tree skeleton. Parent index identifies which earlier
    node this connects to (root has parent=-1). Each node carries a 3D
    position and a skin radius."""

    position: Vector
    radius: float
    parent: int  # index into the skeleton list, or -1 for root


_TRUNK_ARCHETYPES = ("straight", "no_branch", "curved")


def _build_pine_skeleton(
    rng: random.Random,
    trunk_height: float,
    trunk_segments: int,
    trunk_radius_base: float,
    trunk_radius_top: float,
    n_branch_layers: int,
    branches_per_layer_range: tuple[int, int],
    branch_length_range: tuple[float, float],
    branch_droop_range: tuple[float, float],
    branch_taper: float,
    branch_lower_z_fraction: float,
    trunk_archetype: str = "straight",
    curve_amplitude: float = 0.5,
) -> list[_SkeletonNode]:
    """Pine archetype: tall straight trunk, layers of roughly-horizontal
    drooping branches stacked upward. Lower-trunk has no branches.

    Mirrors Sapling's level-based structure: level 0 = trunk, level 1 =
    main branches. Skipping level-2 (sub-branches) — at low poly they
    don't survive remesh anyway; the foliage clump replaces them
    visually.
    """
    if trunk_archetype not in _TRUNK_ARCHETYPES:
        raise ValueError(
            f"unknown trunk_archetype {trunk_archetype!r}; "
            f"valid: {_TRUNK_ARCHETYPES}"
        )
    # `no_branch` archetype: skip branch generation entirely.
    if trunk_archetype == "no_branch":
        n_branch_layers = 0

    # `curved` archetype: pick a yaw direction once and apply a sine-wave
    # horizontal offset along the trunk to produce an S-curve (bonsai
    # feel). Amplitude given in metres; phase=2π gives one full S over
    # trunk_height.
    curved = trunk_archetype == "curved"
    curve_yaw = rng.uniform(0, 2 * math.pi) if curved else 0.0

    nodes: list[_SkeletonNode] = []

    # --- Trunk (level 0) ---
    for i in range(trunk_segments + 1):
        t = i / trunk_segments
        wobble = 0.04 * trunk_height * t
        x = rng.uniform(-wobble, wobble)
        y = rng.uniform(-wobble, wobble)
        if curved:
            offset = curve_amplitude * math.sin(t * 2 * math.pi)
            x += offset * math.cos(curve_yaw)
            y += offset * math.sin(curve_yaw)
        z = trunk_height * t
        radius = trunk_radius_base * (1 - t) + trunk_radius_top * t
        parent = i - 1
        nodes.append(_SkeletonNode(Vector((x, y, z)), radius, parent))
    trunk_top_idx = len(nodes) - 1

    # --- Branches (level 1) ---
    # Distribute branch layers across the upper (1 - branch_lower_z_fraction)
    # of the trunk. Each layer pairs one or more branches off a trunk node.
    if n_branch_layers > 0:
        # Pick `n_branch_layers` distinct trunk segments above the lower fraction
        lowest_branch_seg = max(1, int(trunk_segments * branch_lower_z_fraction))
        candidate_segs = list(range(lowest_branch_seg, trunk_segments + 1))
        layer_segs = sorted(rng.sample(candidate_segs, min(n_branch_layers, len(candidate_segs))))
        for layer_idx, seg in enumerate(layer_segs):
            parent_node_idx = seg
            parent_node = nodes[parent_node_idx]
            n_branches = rng.randint(*branches_per_layer_range)
            base_yaw = rng.uniform(0, 2 * math.pi)
            for b in range(n_branches):
                yaw = base_yaw + b * (2 * math.pi / n_branches) + rng.uniform(-0.2, 0.2)
                # Pitch: from horizontal, drooping downward
                droop = rng.uniform(*branch_droop_range)
                length = rng.uniform(*branch_length_range)
                # Branches get shorter higher up (pine cone tapers)
                height_factor = 1.0 - 0.7 * (parent_node.position.z / trunk_height)
                length *= max(0.4, height_factor)
                # Two-segment branch: parent → mid → tip
                segs = 2
                prev_idx = parent_node_idx
                prev_pos = parent_node.position
                base_branch_radius = parent_node.radius * 0.45
                for s in range(1, segs + 1):
                    t = s / segs
                    horizontal = math.cos(droop) * length * t
                    vertical = -math.sin(droop) * length * t
                    pos = parent_node.position + Vector(
                        (
                            horizontal * math.cos(yaw),
                            horizontal * math.sin(yaw),
                            vertical,
                        )
                    )
                    radius = base_branch_radius * (1 - t * branch_taper)
                    radius = max(radius, 0.005)
                    nodes.append(_SkeletonNode(pos, radius, prev_idx))
                    prev_idx = len(nodes) - 1
                    prev_pos = pos

    return nodes


# ---------------------------------------------------------------------------
# Mesh — skeleton → bmesh → SKIN modifier → mesh
# ---------------------------------------------------------------------------


def _skeleton_to_skin_object(name: str, skeleton: list[_SkeletonNode]) -> bpy.types.Object:
    """Convert a list of skeleton nodes into a Blender object whose SKIN
    modifier produces the tube mesh."""
    me = bpy.data.meshes.new(f"{name}_Skin")
    bm = bmesh.new()

    bm_verts = []
    for node in skeleton:
        bm_verts.append(bm.verts.new(node.position))
    bm.verts.ensure_lookup_table()
    for i, node in enumerate(skeleton):
        if node.parent >= 0:
            try:
                bm.edges.new((bm_verts[node.parent], bm_verts[i]))
            except ValueError:
                # Edge already exists; harmless
                pass

    bm.to_mesh(me)
    bm.free()

    obj = bpy.data.objects.new(name, me)
    # Use scene.collection — context.collection can be None in headless.
    bpy.context.scene.collection.objects.link(obj)

    # Add SKIN modifier — this is the heart of the Sapling-style approach.
    # The modifier reads per-vertex radii from a "skin_vertices" layer that
    # Blender creates automatically when the modifier is added.
    skin_mod = obj.modifiers.new("Skin", "SKIN")
    skin_mod.use_smooth_shade = False  # we'll flat_shade later anyway

    # Now set per-vertex radii. The skin layer exists once the modifier is
    # added, but it's accessed via obj.data.skin_vertices[0].
    skin_layer = obj.data.skin_vertices[0].data
    for i, node in enumerate(skeleton):
        skin_layer[i].radius = (node.radius, node.radius)
        if node.parent < 0:
            skin_layer[i].use_root = True

    # Apply the modifier so we have a real mesh we can flat-shade and
    # decimate downstream. butil.apply_modifiers() invalidates the
    # `obj` Python reference under some Blender 4.2 conditions
    # (StructRNA removed); use direct ops with explicit selection so
    # the reference survives.
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier="Skin")

    return obj


# ---------------------------------------------------------------------------
# Foliage archetypes — each implements a different stylized clump shape.
# All emit faces appended directly to the existing target.data mesh as a
# single object (no instancing), and tag the new faces' smooth flag based
# on the smooth_shade arg.
# ---------------------------------------------------------------------------


def _foliage_round_ball(
    bm,
    crown_position: Vector,
    crown_radius: float,
    crown_height: float,
    icosphere_subdivisions: int,
    rng: random.Random,
    smooth_shade: bool,
) -> int:
    """A single soft squashed icosphere — the canonical stylized
    "broadleaf-tree-like-a-balloon" look. Returns # of faces added."""
    prev_face_count = len(bm.faces)
    rxy = crown_radius
    rz = crown_height * 0.5  # squash slightly
    center = Vector((crown_position.x, crown_position.y, crown_position.z + rz))
    result = bmesh.ops.create_icosphere(
        bm, subdivisions=icosphere_subdivisions, radius=1.0
    )
    new_verts = result["verts"]
    for v in new_verts:
        v.co.x = v.co.x * rxy + center.x
        v.co.y = v.co.y * rxy + center.y
        v.co.z = v.co.z * rz + center.z
    bm.faces.ensure_lookup_table()
    if smooth_shade:
        for j in range(prev_face_count, len(bm.faces)):
            bm.faces[j].smooth = True
    return len(bm.faces) - prev_face_count


def _foliage_umbrella(
    bm,
    crown_position: Vector,
    crown_radius: float,
    crown_height: float,
    icosphere_subdivisions: int,
    rng: random.Random,
    smooth_shade: bool,
) -> int:
    """A wide flat dome — the canopy / mushroom-cap look. Single
    icosphere stretched horizontally and squashed vertically. Returns #
    of faces added."""
    prev_face_count = len(bm.faces)
    rxy = crown_radius * 1.4
    rz = crown_height * 0.30  # pancaked
    center = Vector((crown_position.x, crown_position.y, crown_position.z + rz))
    result = bmesh.ops.create_icosphere(
        bm, subdivisions=icosphere_subdivisions, radius=1.0
    )
    new_verts = result["verts"]
    for v in new_verts:
        v.co.x = v.co.x * rxy + center.x
        v.co.y = v.co.y * rxy + center.y
        v.co.z = v.co.z * rz + center.z
    bm.faces.ensure_lookup_table()
    if smooth_shade:
        for j in range(prev_face_count, len(bm.faces)):
            bm.faces[j].smooth = True
    return len(bm.faces) - prev_face_count


def _foliage_crystal(
    bm,
    crown_position: Vector,
    crown_radius: float,
    crown_height: float,
    icosphere_subdivisions: int,
    rng: random.Random,
    smooth_shade: bool,
) -> int:
    """An angular vertical icosphere — sharp/spire/crystal look.
    Subdivisions=0 by default would give a base icosphere; combined
    with vertical stretch this reads as a faceted crystal. Returns #
    of faces added."""
    prev_face_count = len(bm.faces)
    rxy = crown_radius * 0.8
    rz = crown_height * 0.7  # tall and narrow
    center = Vector((crown_position.x, crown_position.y, crown_position.z + rz))
    # Crystal is intentionally faceted — subdivision=0 gives a base
    # 20-face icosahedron with sharp edges. Caller-provided subdivisions
    # are still honored if greater.
    subdivs = max(icosphere_subdivisions, 0)
    result = bmesh.ops.create_icosphere(
        bm, subdivisions=subdivs, radius=1.0
    )
    new_verts = result["verts"]
    for v in new_verts:
        v.co.x = v.co.x * rxy + center.x
        v.co.y = v.co.y * rxy + center.y
        v.co.z = v.co.z * rz + center.z
    bm.faces.ensure_lookup_table()
    # Crystal is the one archetype that benefits from FLAT shading
    # regardless of smooth_shade — the angular look needs the facets
    # visible. Caller can still override by editing the faces post-hoc.
    for j in range(prev_face_count, len(bm.faces)):
        bm.faces[j].smooth = False
    return len(bm.faces) - prev_face_count


def _foliage_bush(
    bm,
    crown_position: Vector,
    crown_radius: float,
    crown_height: float,
    icosphere_subdivisions: int,
    rng: random.Random,
    smooth_shade: bool,
) -> int:
    """A clump of 3–5 overlapping small icospheres at random offsets —
    organic-looking shrub / messy bush. Returns # of faces added."""
    n = rng.randint(3, 5)
    total_added = 0
    base_radius = crown_radius * 0.55
    for _ in range(n):
        prev_face_count = len(bm.faces)
        rxy = base_radius * rng.uniform(0.7, 1.2)
        rz = base_radius * rng.uniform(0.7, 1.0)
        ox = rng.uniform(-0.5, 0.5) * crown_radius
        oy = rng.uniform(-0.5, 0.5) * crown_radius
        oz = rng.uniform(0.0, 0.6) * crown_height
        center = Vector(
            (crown_position.x + ox, crown_position.y + oy, crown_position.z + oz + rz)
        )
        result = bmesh.ops.create_icosphere(
            bm, subdivisions=icosphere_subdivisions, radius=1.0
        )
        new_verts = result["verts"]
        for v in new_verts:
            v.co.x = v.co.x * rxy + center.x
            v.co.y = v.co.y * rxy + center.y
            v.co.z = v.co.z * rz + center.z
        bm.faces.ensure_lookup_table()
        if smooth_shade:
            for j in range(prev_face_count, len(bm.faces)):
                bm.faces[j].smooth = True
        total_added += len(bm.faces) - prev_face_count
    return total_added


# ---------------------------------------------------------------------------
# Pine cone foliage + dispatcher
# ---------------------------------------------------------------------------


def _foliage_pine_cone(
    bm,
    crown_position: Vector,
    crown_radius: float,
    crown_height: float,
    icosphere_subdivisions: int,
    rng: random.Random,
    smooth_shade: bool,
    layers: int = 4,
) -> int:
    """Original Firewatch-style stacked icospheres forming a pine cone
    silhouette. Each layer is squashed (wider than tall), narrowing as
    we go up. Returns # of faces added."""
    initial_face_count = len(bm.faces)
    z_per_layer = crown_height / max(layers, 1)
    for i in range(layers):
        t = i / max(layers - 1, 1)
        z = crown_position.z + i * z_per_layer
        rxy = crown_radius * (1.0 - 0.55 * t)
        rz = z_per_layer * 0.7
        jx = rng.uniform(-0.1, 0.1) * crown_radius
        jy = rng.uniform(-0.1, 0.1) * crown_radius
        center = Vector((crown_position.x + jx, crown_position.y + jy, z + rz))

        prev_face_count = len(bm.faces)
        result = bmesh.ops.create_icosphere(
            bm, subdivisions=icosphere_subdivisions, radius=1.0
        )
        new_verts = result["verts"]
        for v in new_verts:
            v.co.x = v.co.x * rxy + center.x
            v.co.y = v.co.y * rxy + center.y
            v.co.z = v.co.z * rz + center.z
        bm.faces.ensure_lookup_table()
        if smooth_shade:
            for j in range(prev_face_count, len(bm.faces)):
                bm.faces[j].smooth = True
    return len(bm.faces) - initial_face_count


# Map archetype name → builder function. All builders take the same args
# so the dispatch site doesn't need archetype-specific branching.
_FOLIAGE_BUILDERS = {
    "pine_cone":  _foliage_pine_cone,
    "round_ball": _foliage_round_ball,
    "umbrella":   _foliage_umbrella,
    "crystal":    _foliage_crystal,
    "bush":       _foliage_bush,
}


def _add_foliage(
    target: bpy.types.Object,
    archetype: str,
    crown_position: Vector,
    crown_radius: float,
    crown_height: float,
    layers: int,
    icosphere_subdivisions: int,
    rng: random.Random,
    smooth_shade: bool = True,
) -> tuple[int, int]:
    """Append a foliage clump of the given `archetype` to `target`'s mesh.
    Returns (trunk_face_count, foliage_face_count) — caller sets
    material_index=1 on the foliage face range after bm.to_mesh."""
    if archetype not in _FOLIAGE_BUILDERS:
        raise ValueError(
            f"unknown foliage archetype {archetype!r}; valid: {list(_FOLIAGE_BUILDERS)}"
        )
    trunk_face_count = len(target.data.polygons)

    bm = bmesh.new()
    bm.from_mesh(target.data)
    bm.faces.ensure_lookup_table()

    builder = _FOLIAGE_BUILDERS[archetype]
    if archetype == "pine_cone":
        builder(
            bm, crown_position, crown_radius, crown_height,
            icosphere_subdivisions, rng, smooth_shade, layers=layers,
        )
    else:
        builder(
            bm, crown_position, crown_radius, crown_height,
            icosphere_subdivisions, rng, smooth_shade,
        )

    bm.to_mesh(target.data)
    bm.free()
    foliage_face_count = len(target.data.polygons) - trunk_face_count
    return trunk_face_count, foliage_face_count


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class NativeLowPolyTreeFactory(AssetFactory):
    """Sapling-derived native low-poly tree factory.

    Constructor knobs (sapling-equivalents in parens):

        factory_seed
        archetype : "pine"  — currently the only archetype implemented
        trunk_height : float = 6.0
            Total trunk length, m. (sapling: length[0] * scaleVal)
        trunk_segments : int = 7
            Nodes along trunk. (sapling: curveRes[0])
        trunk_radius_base : float = 0.18
            Trunk radius at base, m. (sapling: ratio * scaleVal)
        trunk_radius_top : float = 0.025
            Trunk radius at top, m. Implies taper.
        n_branch_layers : int = 6
            Number of layers of branches stacked vertically. Each
            layer fans branches off one trunk node. (sapling:
            implicit in branches[1] and curveRes[0])
        branches_per_layer : tuple[int, int] = (3, 5)
            Min/max number of branches per layer.
        branch_length : tuple[float, float] = (0.7, 1.6)
            Min/max branch length, m.
        branch_droop : tuple[float, float] = (0.10, 0.55)
            Min/max droop angle in radians, from horizontal.
            (sapling: downAngle[1])
        branch_taper : float = 0.5
            Branch radius decay along its length. 0 = no taper, 1 =
            tapers to zero. (sapling: taper[1])
        branch_lower_z_fraction : float = 0.30
            Branches don't start until this fraction of trunk height.
            (sapling: baseSize)
        foliage_layers : int = 4
            Stacked icospheres in the crown. Pine-cone shape.
        foliage_radius : float = 1.6
        foliage_height : float = 3.0
        foliage_icosphere_subdivisions : int = 1
            1 = 80 polys per sphere. 2 = 320 polys.
        target_polys : int | None = None
            Optional polycount cap via DECIMATE COLLAPSE after meshing.
        palette_color : str | None = "foliage_pine"
            Single Maquette palette color applied to the whole mesh.
    """

    def __init__(
        self,
        factory_seed,
        archetype: str = "pine",
        trunk_archetype: str = "straight",
        trunk_curve_amplitude: float = 0.5,
        trunk_height: float = 6.0,
        trunk_segments: int = 7,
        trunk_radius_base: float = 0.18,
        trunk_radius_top: float = 0.025,
        n_branch_layers: int = 6,
        branches_per_layer: tuple[int, int] = (3, 5),
        branch_length: tuple[float, float] = (0.7, 1.6),
        branch_droop: tuple[float, float] = (0.10, 0.55),
        branch_taper: float = 0.5,
        branch_lower_z_fraction: float | None = None,
        crown_z_fraction: float = 0.45,
        foliage_archetype: str = "pine_cone",
        foliage_layers: int = 4,
        foliage_radius: float = 1.6,
        foliage_height: float = 3.0,
        foliage_icosphere_subdivisions: int = 1,
        smooth_foliage: bool = True,
        target_polys: int | None = None,
        trunk_color: str | None = "rock_shadow",
        palette_color: str | None = "foliage_pine",
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if archetype != "pine":
            raise ValueError(f"unsupported archetype {archetype!r}; only 'pine' for now")
        self.archetype = archetype
        if trunk_archetype not in _TRUNK_ARCHETYPES:
            raise ValueError(
                f"unknown trunk_archetype {trunk_archetype!r}; "
                f"valid: {_TRUNK_ARCHETYPES}"
            )
        self.trunk_archetype = trunk_archetype
        self.trunk_curve_amplitude = trunk_curve_amplitude
        self.trunk_height = trunk_height
        self.trunk_segments = trunk_segments
        self.trunk_radius_base = trunk_radius_base
        self.trunk_radius_top = trunk_radius_top
        self.n_branch_layers = n_branch_layers
        self.branches_per_layer = branches_per_layer
        self.branch_length = branch_length
        self.branch_droop = branch_droop
        self.branch_taper = branch_taper
        # Default branch_lower_z_fraction to crown_z_fraction so branches
        # only spawn inside the foliage volume by default — no exposed
        # branches below the foliage clump. Override to push branches
        # lower if the look calls for it.
        self.branch_lower_z_fraction = (
            branch_lower_z_fraction
            if branch_lower_z_fraction is not None
            else crown_z_fraction
        )
        self.crown_z_fraction = crown_z_fraction
        if foliage_archetype not in _FOLIAGE_BUILDERS:
            raise ValueError(
                f"unknown foliage_archetype {foliage_archetype!r}; valid: "
                f"{list(_FOLIAGE_BUILDERS)}"
            )
        self.foliage_archetype = foliage_archetype
        self.foliage_layers = foliage_layers
        self.foliage_radius = foliage_radius
        self.foliage_height = foliage_height
        self.foliage_icosphere_subdivisions = foliage_icosphere_subdivisions
        self.smooth_foliage = smooth_foliage
        self.target_polys = target_polys
        self.trunk_color = trunk_color
        self.palette_color = palette_color

    # AssetFactory interface — placeholder is a lightweight stand-in (Empty);
    # the real tree mesh is built in create_asset. AssetFactory.spawn_asset
    # deletes the placeholder after create_asset returns, and only the
    # asset survives — so the two MUST be different objects, otherwise our
    # tree gets garbage-collected.
    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"NativeTree({self.factory_seed})_placeholder",
            None,  # Empty
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)

        # The trunk skeleton stops a small distance INSIDE the foliage
        # volume so the trunk top is never visually exposed regardless
        # of which foliage archetype the caller picks (umbrella ends
        # earlier than crystal etc.). The user's `trunk_height`
        # parameter becomes the total conceptual tree height; the
        # actual skeleton is shorter.
        crown_z_base = self.trunk_height * self.crown_z_fraction
        trunk_skel_height = crown_z_base + min(0.6, self.foliage_height * 0.3)

        skeleton = _build_pine_skeleton(
            rng=rng,
            trunk_height=trunk_skel_height,
            trunk_segments=self.trunk_segments,
            trunk_radius_base=self.trunk_radius_base,
            trunk_radius_top=self.trunk_radius_top,
            n_branch_layers=self.n_branch_layers,
            branches_per_layer_range=self.branches_per_layer,
            branch_length_range=self.branch_length,
            branch_droop_range=self.branch_droop,
            branch_taper=self.branch_taper,
            # Branch lower fraction is relative to the *skeleton* height,
            # not the conceptual trunk_height. Recompute so branches still
            # only spawn at the upper end of the visible trunk.
            branch_lower_z_fraction=min(0.99, crown_z_base / max(trunk_skel_height, 1e-6)),
            trunk_archetype=self.trunk_archetype,
            curve_amplitude=self.trunk_curve_amplitude,
        )

        obj = _skeleton_to_skin_object(
            name=f"NativeTree({self.factory_seed})",
            skeleton=skeleton,
        )

        # Pre-allocate 2 material slots BEFORE setting any polygon
        # material_index. Blender silently clamps material_index to a
        # valid slot range when the slot doesn't exist, so any
        # material_index=1 we set here without slots in place would be
        # reset to 0 silently. apply_palette_slots replaces these
        # placeholders later with real palette materials.
        while len(obj.data.materials) < 2:
            obj.data.materials.append(None)

        # Foliage anchor: use the trunk-top node's horizontal position so
        # curved trunks carry their foliage with them. crown_z_base
        # remains based on conceptual trunk_height (the foliage's vertical
        # placement is decoupled from the trunk's lean).
        trunk_top_node = skeleton[self.trunk_segments]
        crown_pos = Vector((
            trunk_top_node.position.x,
            trunk_top_node.position.y,
            crown_z_base,
        ))
        trunk_count, foliage_count = _add_foliage(
            obj,
            archetype=self.foliage_archetype,
            crown_position=crown_pos,
            crown_radius=self.foliage_radius,
            crown_height=self.foliage_height,
            layers=self.foliage_layers,
            icosphere_subdivisions=self.foliage_icosphere_subdivisions,
            rng=rng,
            smooth_shade=self.smooth_foliage,
        )

        # Tag foliage faces with material_index=1 directly on the mesh.
        # Doing this BEFORE decimate is important — decimate preserves
        # material_index through merges. Doing it on bmesh and writing
        # back via bm.to_mesh did NOT stick in Blender 4.2.
        for idx in range(trunk_count, trunk_count + foliage_count):
            if idx < len(obj.data.polygons):
                obj.data.polygons[idx].material_index = 1

        # Optional polycount cap. Decimate COLLAPSE preserves face.smooth
        # flags through merges (new faces inherit from neighbors), so the
        # smooth-foliage / flat-trunk split survives this step.
        if self.target_polys is not None and self.target_polys > 0:
            current = max(len(obj.data.polygons), 1)
            if current > self.target_polys:
                ratio = self.target_polys / current
                butil.modify_mesh(
                    obj,
                    "DECIMATE",
                    decimate_type="COLLAPSE",
                    ratio=ratio,
                    apply=True,
                )

        # NOTE: deliberately do NOT call flat_shade(obj) here — that would
        # set use_smooth=False on every poly, including foliage faces we
        # just marked smooth in _add_pine_foliage. The skin modifier output
        # is already flat, and the foliage faces carry their smooth flag
        # explicitly. Calling flat_shade would defeat smooth_foliage=True.

        # Material slots: trunk faces stay at material_index=0 (slot 0),
        # foliage faces were tagged material_index=1 in _add_pine_foliage
        # (slot 1). If the caller wants two-tone (default), use both
        # palette keys; otherwise fall back to single-color apply_palette.
        if self.trunk_color is not None and self.palette_color is not None:
            apply_palette_slots(obj, [self.trunk_color, self.palette_color])
        elif self.palette_color is not None:
            apply_palette(obj, self.palette_color)
        elif self.trunk_color is not None:
            apply_palette(obj, self.trunk_color)
        return obj
