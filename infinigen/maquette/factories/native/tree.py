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

from ...lowpoly import flat_shade
from ...materials import apply_palette


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
) -> list[_SkeletonNode]:
    """Pine archetype: tall straight trunk, layers of roughly-horizontal
    drooping branches stacked upward. Lower-trunk has no branches.

    Mirrors Sapling's level-based structure: level 0 = trunk, level 1 =
    main branches. Skipping level-2 (sub-branches) — at low poly they
    don't survive remesh anyway; the foliage clump replaces them
    visually.
    """
    nodes: list[_SkeletonNode] = []

    # --- Trunk (level 0) ---
    for i in range(trunk_segments + 1):
        t = i / trunk_segments
        # Slight horizontal wobble, growing with height
        wobble = 0.04 * trunk_height * t
        x = rng.uniform(-wobble, wobble)
        y = rng.uniform(-wobble, wobble)
        z = trunk_height * t
        radius = trunk_radius_base * (1 - t) + trunk_radius_top * t
        parent = i - 1  # chain
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
    bpy.context.collection.objects.link(obj)

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
    # decimate downstream. The skin modifier doesn't need a UI context
    # so this is safe in headless.
    butil.apply_modifiers(obj)

    return obj


# ---------------------------------------------------------------------------
# Foliage — stacked icospheres (Firewatch deformed-balloon style)
# ---------------------------------------------------------------------------


def _add_pine_foliage(
    target: bpy.types.Object,
    crown_position: Vector,
    crown_radius: float,
    crown_height: float,
    layers: int,
    icosphere_subdivisions: int,
    rng: random.Random,
):
    """Stack `layers` squashed icospheres up from `crown_position` to form a
    pine-cone-shaped foliage volume. All geometry is appended to `target`'s
    mesh as a SINGLE OBJECT (not instanced). Pure Firewatch-style
    deformed-balloon foliage."""
    # Operate on the existing mesh data to keep one object
    bm = bmesh.new()
    bm.from_mesh(target.data)

    # Each layer: one squashed icosphere, narrower as we go up
    z_per_layer = crown_height / max(layers, 1)
    for i in range(layers):
        t = i / max(layers - 1, 1)
        z = crown_position.z + i * z_per_layer
        # Tapering radius (wide at bottom, narrow at top)
        rxy = crown_radius * (1.0 - 0.55 * t)
        rz = z_per_layer * 0.7  # shallow
        # Slight per-layer position jitter
        jx = rng.uniform(-0.1, 0.1) * crown_radius
        jy = rng.uniform(-0.1, 0.1) * crown_radius
        center = Vector((crown_position.x + jx, crown_position.y + jy, z + rz))

        result = bmesh.ops.create_icosphere(
            bm, subdivisions=icosphere_subdivisions, radius=1.0
        )
        new_verts = result["verts"]
        for v in new_verts:
            v.co.x = v.co.x * rxy + center.x
            v.co.y = v.co.y * rxy + center.y
            v.co.z = v.co.z * rz + center.z

    bm.to_mesh(target.data)
    bm.free()


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
        trunk_height: float = 6.0,
        trunk_segments: int = 7,
        trunk_radius_base: float = 0.18,
        trunk_radius_top: float = 0.025,
        n_branch_layers: int = 6,
        branches_per_layer: tuple[int, int] = (3, 5),
        branch_length: tuple[float, float] = (0.7, 1.6),
        branch_droop: tuple[float, float] = (0.10, 0.55),
        branch_taper: float = 0.5,
        branch_lower_z_fraction: float = 0.30,
        foliage_layers: int = 4,
        foliage_radius: float = 1.6,
        foliage_height: float = 3.0,
        foliage_icosphere_subdivisions: int = 1,
        target_polys: int | None = None,
        palette_color: str | None = "foliage_pine",
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if archetype != "pine":
            raise ValueError(f"unsupported archetype {archetype!r}; only 'pine' for now")
        self.archetype = archetype
        self.trunk_height = trunk_height
        self.trunk_segments = trunk_segments
        self.trunk_radius_base = trunk_radius_base
        self.trunk_radius_top = trunk_radius_top
        self.n_branch_layers = n_branch_layers
        self.branches_per_layer = branches_per_layer
        self.branch_length = branch_length
        self.branch_droop = branch_droop
        self.branch_taper = branch_taper
        self.branch_lower_z_fraction = branch_lower_z_fraction
        self.foliage_layers = foliage_layers
        self.foliage_radius = foliage_radius
        self.foliage_height = foliage_height
        self.foliage_icosphere_subdivisions = foliage_icosphere_subdivisions
        self.target_polys = target_polys
        self.palette_color = palette_color

    # AssetFactory interface — we do everything in spawn_asset for simplicity;
    # there's no separate placeholder/finalize step needed for native trees.
    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        return self._build()

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        if placeholder is None:
            return self._build()
        return placeholder

    def _build(self) -> bpy.types.Object:
        rng = random.Random(self.factory_seed)

        skeleton = _build_pine_skeleton(
            rng=rng,
            trunk_height=self.trunk_height,
            trunk_segments=self.trunk_segments,
            trunk_radius_base=self.trunk_radius_base,
            trunk_radius_top=self.trunk_radius_top,
            n_branch_layers=self.n_branch_layers,
            branches_per_layer_range=self.branches_per_layer,
            branch_length_range=self.branch_length,
            branch_droop_range=self.branch_droop,
            branch_taper=self.branch_taper,
            branch_lower_z_fraction=self.branch_lower_z_fraction,
        )

        obj = _skeleton_to_skin_object(
            name=f"NativeTree({self.factory_seed})",
            skeleton=skeleton,
        )

        # Foliage clump — top of the trunk. Place crown so its bottom layer
        # sits roughly at the highest branch-attached trunk node and extends
        # upward, hiding the trunk top.
        crown_z_base = self.trunk_height * 0.55
        crown_pos = Vector((skeleton[0].position.x, skeleton[0].position.y, crown_z_base))
        _add_pine_foliage(
            obj,
            crown_position=crown_pos,
            crown_radius=self.foliage_radius,
            crown_height=self.foliage_height,
            layers=self.foliage_layers,
            icosphere_subdivisions=self.foliage_icosphere_subdivisions,
            rng=rng,
        )

        # Optional polycount cap
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

        flat_shade(obj)
        if self.palette_color is not None:
            apply_palette(obj, self.palette_color)
        return obj
