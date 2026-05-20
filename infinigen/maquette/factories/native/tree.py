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

from ...density import (
    n_along_axis,
    n_subdivisions,
    target_edge_for_bbox,
)
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
        # Lenient fallback rather than crash. Sonnet has been
        # observed to hallucinate plausible-sounding archetype
        # names despite the factories_guide brief listing the
        # valid set; killing a 6-minute build over a one-line
        # archetype typo wastes a generation. Substitute the
        # canonical default and warn to stderr.
        import sys
        print(
            f"[trunk_archetype] WARN: unknown trunk_archetype "
            f"{trunk_archetype!r}; falling back to {_TRUNK_ARCHETYPES[0]!r}. "
            f"Valid: {_TRUNK_ARCHETYPES}",
            file=sys.stderr,
        )
        trunk_archetype = _TRUNK_ARCHETYPES[0]
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
    rxy = crown_radius * 1.12
    rz = crown_height * 0.34  # broad canopy, not a pure pancake
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


def _add_foliage_ellipsoid(
    bm,
    *,
    center: Vector,
    radius_xy: float,
    radius_z: float,
    subdivisions: int,
    smooth_shade: bool,
) -> int:
    """Append one low-poly ellipsoid and return the face count added."""
    prev_face_count = len(bm.faces)
    result = bmesh.ops.create_icosphere(
        bm, subdivisions=max(0, subdivisions), radius=1.0
    )
    for v in result["verts"]:
        v.co.x = v.co.x * radius_xy + center.x
        v.co.y = v.co.y * radius_xy + center.y
        v.co.z = v.co.z * radius_z + center.z
    bm.faces.ensure_lookup_table()
    if smooth_shade:
        for j in range(prev_face_count, len(bm.faces)):
            bm.faces[j].smooth = True
    return len(bm.faces) - prev_face_count


def _add_frustum(
    bm,
    *,
    center: Vector,
    radius_bottom: float,
    radius_top: float,
    height: float,
    sides: int,
    yaw: float = 0.0,
    cap_top: bool = True,
    cap_bottom: bool = False,
    smooth_shade: bool = False,
) -> int:
    """Append a faceted vertical frustum/cone tier."""
    prev_face_count = len(bm.faces)
    sides = max(3, int(sides))
    bottom = []
    top = []
    z0 = center.z - height * 0.5
    z1 = center.z + height * 0.5
    for i in range(sides):
        a = yaw + i * (2 * math.pi / sides)
        ca = math.cos(a)
        sa = math.sin(a)
        bottom.append(bm.verts.new((center.x + ca * radius_bottom, center.y + sa * radius_bottom, z0)))
        top.append(bm.verts.new((center.x + ca * radius_top, center.y + sa * radius_top, z1)))
    bm.verts.ensure_lookup_table()
    for i in range(sides):
        face = bm.faces.new((bottom[i], bottom[(i + 1) % sides], top[(i + 1) % sides], top[i]))
        face.smooth = smooth_shade
    if cap_top and radius_top > 0.001:
        face = bm.faces.new(tuple(reversed(top)))
        face.smooth = smooth_shade
    if cap_bottom:
        face = bm.faces.new(tuple(bottom))
        face.smooth = smooth_shade
    bm.faces.ensure_lookup_table()
    return len(bm.faces) - prev_face_count


def _add_leaf_card(
    bm,
    *,
    center: Vector,
    direction: Vector,
    length: float,
    width: float,
    lift: float = 0.0,
    droop: float = 0.0,
) -> int:
    """Append one diamond-shaped low-poly leaf plate.

    This is intentionally geometry, not an alpha plane. The face reads as
    an individual clump/leaf mass and avoids the stretched-sphere look.
    """
    direction = Vector((direction.x, direction.y, 0.0))
    if direction.length < 1e-6:
        direction = Vector((1.0, 0.0, 0.0))
    direction.normalize()
    side = Vector((-direction.y, direction.x, 0.0))
    base = center - direction * (length * 0.42) + Vector((0.0, 0.0, lift * 0.25))
    left = center + side * width + Vector((0.0, 0.0, lift))
    tip = center + direction * (length * 0.58) - Vector((0.0, 0.0, droop))
    right = center - side * width + Vector((0.0, 0.0, lift * 0.35))
    points = (base, left, tip, right)
    verts = [bm.verts.new(p) for p in points]
    bm.verts.ensure_lookup_table()
    bm.faces.new(tuple(verts))
    # Blender materials are two-sided in many viewport modes, but Cycles
    # still reads the face normal for lighting. Add a back face so
    # foliage cards don't disappear at unlucky camera angles.
    back_verts = [bm.verts.new(p) for p in points]
    bm.verts.ensure_lookup_table()
    bm.faces.new(tuple(reversed(back_verts)))
    bm.faces.ensure_lookup_table()
    return 2


def _add_hanging_strip(
    bm,
    *,
    top_center: Vector,
    direction: Vector,
    length: float,
    width: float,
    bend: float,
) -> int:
    """Append a vertical tapered leaf curtain for willow-like trees."""
    direction = Vector((direction.x, direction.y, 0.0))
    if direction.length < 1e-6:
        direction = Vector((1.0, 0.0, 0.0))
    direction.normalize()
    side = Vector((-direction.y, direction.x, 0.0))
    bottom_center = top_center + direction * bend - Vector((0.0, 0.0, length))
    points = (
        top_center - side * width,
        top_center + side * width,
        bottom_center + side * width * 0.42,
        bottom_center - side * width * 0.42,
    )
    verts = [bm.verts.new(p) for p in points]
    bm.verts.ensure_lookup_table()
    bm.faces.new(tuple(verts))
    back_verts = [bm.verts.new(p) for p in points]
    bm.verts.ensure_lookup_table()
    bm.faces.new(tuple(reversed(back_verts)))
    bm.faces.ensure_lookup_table()
    return 2


def _foliage_layered_broadleaf(
    bm,
    crown_position: Vector,
    crown_radius: float,
    crown_height: float,
    icosphere_subdivisions: int,
    rng: random.Random,
    smooth_shade: bool,
) -> int:
    """Several overlapping leaf masses around the branch structure.

    This is deliberately not a single balloon and not a pine stack: the
    silhouette has side lobes, small gaps, and a broader upper canopy so
    oaks/maples read differently from pines at scene distance.
    """
    total_added = 0
    n = rng.randint(6, 9)
    base_angle = rng.uniform(0, 2 * math.pi)
    for i in range(n):
        t = i / max(n - 1, 1)
        ring = 0.35 + 0.45 * math.sin(t * math.pi)
        angle = base_angle + i * 2.399963 + rng.uniform(-0.35, 0.35)
        ox = math.cos(angle) * crown_radius * ring * rng.uniform(0.35, 0.85)
        oy = math.sin(angle) * crown_radius * ring * rng.uniform(0.35, 0.85)
        oz = crown_height * (0.16 + 0.72 * t) + rng.uniform(-0.08, 0.08) * crown_height
        radius_xy = crown_radius * rng.uniform(0.42, 0.68) * (1.08 - 0.22 * t)
        radius_z = crown_height * rng.uniform(0.13, 0.20)
        total_added += _add_foliage_ellipsoid(
            bm,
            center=Vector((crown_position.x + ox, crown_position.y + oy, crown_position.z + oz)),
            radius_xy=radius_xy,
            radius_z=radius_z,
            subdivisions=icosphere_subdivisions,
            smooth_shade=smooth_shade,
        )
    return total_added


def _foliage_tiered_cones(
    bm,
    crown_position: Vector,
    crown_radius: float,
    crown_height: float,
    icosphere_subdivisions: int,
    rng: random.Random,
    smooth_shade: bool,
) -> int:
    """Stacked low-poly frustum/cone tiers, inspired by game-ready
    conifer assets. This replaces sphere-stacks for pine silhouettes."""
    total_added = 0
    layers = max(3, min(6, int(round(crown_height / max(crown_radius * 0.45, 0.35)))))
    yaw = rng.uniform(0, 2 * math.pi)
    for i in range(layers):
        t = i / max(layers - 1, 1)
        radius = crown_radius * (1.0 - 0.68 * t) * rng.uniform(0.92, 1.08)
        z = crown_position.z + crown_height * (0.10 + 0.82 * t)
        height = crown_height / layers * rng.uniform(0.52, 0.70)
        total_added += _add_frustum(
            bm,
            center=Vector((
                crown_position.x + rng.uniform(-0.035, 0.035) * crown_radius,
                crown_position.y + rng.uniform(-0.035, 0.035) * crown_radius,
                z,
            )),
            radius_bottom=radius,
            radius_top=radius * rng.uniform(0.16, 0.28),
            height=height,
            sides=rng.choice([6, 7, 8]),
            yaw=yaw + i * 0.31,
            cap_top=True,
            cap_bottom=False,
            smooth_shade=False,
        )
    return total_added


def _foliage_leaf_cards(
    bm,
    crown_position: Vector,
    crown_radius: float,
    crown_height: float,
    icosphere_subdivisions: int,
    rng: random.Random,
    smooth_shade: bool,
) -> int:
    """Radial diamond leaf-card canopy.

    Useful for oaks, flowering trees, and shrubs where individual plate
    masses read better than balloons.
    """
    total_added = 0
    total_added += _add_frustum(
        bm,
        center=crown_position + Vector((0.0, 0.0, crown_height * 0.48)),
        radius_bottom=crown_radius * 0.82,
        radius_top=crown_radius * 0.58,
        height=crown_height * 0.26,
        sides=9,
        yaw=rng.uniform(0, 2 * math.pi),
        cap_top=True,
        cap_bottom=False,
        smooth_shade=False,
    )
    rows = 3
    base_angle = rng.uniform(0, 2 * math.pi)
    for row in range(rows):
        t = row / max(rows - 1, 1)
        n = 8 if row == 0 else 7 if row == 1 else 5
        row_radius = crown_radius * (0.95 - 0.25 * t)
        z = crown_height * (0.22 + 0.54 * t)
        for i in range(n):
            angle = base_angle + i * (2 * math.pi / n) + row * 0.37 + rng.uniform(-0.18, 0.18)
            direction = Vector((math.cos(angle), math.sin(angle), 0.0))
            center = (
                crown_position
                + direction * row_radius * rng.uniform(0.28, 0.74)
                + Vector((0.0, 0.0, z + rng.uniform(-0.08, 0.08) * crown_height))
            )
            total_added += _add_leaf_card(
                bm,
                center=center,
                direction=direction,
                length=crown_radius * rng.uniform(0.72, 1.05) * (1.0 - 0.16 * t),
                width=crown_radius * rng.uniform(0.23, 0.36) * (1.0 - 0.10 * t),
                lift=crown_height * rng.uniform(0.02, 0.08),
                droop=crown_height * rng.uniform(0.03, 0.12),
            )
    return total_added


def _foliage_columnar(
    bm,
    crown_position: Vector,
    crown_radius: float,
    crown_height: float,
    icosphere_subdivisions: int,
    rng: random.Random,
    smooth_shade: bool,
) -> int:
    """Tall narrow stacked crown for cypress/poplar silhouettes."""
    total_added = 0
    n = 6
    for i in range(n):
        t = i / max(n - 1, 1)
        radius_profile = 0.35 + 0.65 * math.sin((1.0 - t * 0.72) * math.pi * 0.72)
        radius_xy = crown_radius * max(0.28, radius_profile) * rng.uniform(0.82, 1.08)
        radius_z = crown_height / n * rng.uniform(0.58, 0.78)
        ox = rng.uniform(-0.08, 0.08) * crown_radius
        oy = rng.uniform(-0.08, 0.08) * crown_radius
        oz = crown_height * (0.08 + 0.86 * t)
        total_added += _add_foliage_ellipsoid(
            bm,
            center=Vector((crown_position.x + ox, crown_position.y + oy, crown_position.z + oz)),
            radius_xy=radius_xy,
            radius_z=radius_z,
            subdivisions=icosphere_subdivisions,
            smooth_shade=smooth_shade,
        )
    return total_added


def _foliage_windswept(
    bm,
    crown_position: Vector,
    crown_radius: float,
    crown_height: float,
    icosphere_subdivisions: int,
    rng: random.Random,
    smooth_shade: bool,
) -> int:
    """Asymmetric crown pushed to one side, useful for coasts/ridges."""
    total_added = 0
    wind_angle = rng.uniform(0, 2 * math.pi)
    wind_vec = Vector((math.cos(wind_angle), math.sin(wind_angle), 0.0))
    side_vec = Vector((-math.sin(wind_angle), math.cos(wind_angle), 0.0))
    n = rng.randint(4, 6)
    for i in range(n):
        t = i / max(n - 1, 1)
        push = crown_radius * (0.25 + 0.82 * t)
        side = rng.uniform(-0.22, 0.22) * crown_radius
        vertical = crown_height * (0.20 + 0.62 * t)
        center = (
            crown_position
            + wind_vec * push
            + side_vec * side
            + Vector((0.0, 0.0, vertical))
        )
        total_added += _add_foliage_ellipsoid(
            bm,
            center=center,
            radius_xy=crown_radius * rng.uniform(0.42, 0.62) * (1.05 - 0.2 * t),
            radius_z=crown_height * rng.uniform(0.13, 0.18),
            subdivisions=icosphere_subdivisions,
            smooth_shade=smooth_shade,
        )
    return total_added


def _foliage_none(
    bm,
    crown_position: Vector,
    crown_radius: float,
    crown_height: float,
    icosphere_subdivisions: int,
    rng: random.Random,
    smooth_shade: bool,
) -> int:
    """No foliage at all: winter/dead trees rely on the branch skeleton."""
    return 0


def _foliage_weeping(
    bm,
    crown_position: Vector,
    crown_radius: float,
    crown_height: float,
    icosphere_subdivisions: int,
    rng: random.Random,
    smooth_shade: bool,
) -> int:
    """Weeping willow-style crown with hanging leaf curtains."""
    total_added = 0
    top = crown_position + Vector((0.0, 0.0, crown_height * 0.82))
    total_added += _add_frustum(
        bm,
        center=top,
        radius_bottom=crown_radius * 1.05,
        radius_top=crown_radius * 0.62,
        height=crown_height * 0.20,
        sides=9,
        yaw=rng.uniform(0, 2 * math.pi),
        cap_top=True,
        cap_bottom=False,
        smooth_shade=False,
    )
    n = rng.randint(13, 17)
    base_angle = rng.uniform(0, 2 * math.pi)
    for i in range(n):
        angle = base_angle + i * (2 * math.pi / n) + rng.uniform(-0.16, 0.16)
        radius = crown_radius * rng.uniform(0.45, 0.95)
        direction = Vector((math.cos(angle), math.sin(angle), 0.0))
        top_center = Vector((
            crown_position.x + direction.x * radius,
            crown_position.y + direction.y * radius,
            crown_position.z + crown_height * rng.uniform(0.55, 0.78),
        ))
        total_added += _add_hanging_strip(
            bm,
            top_center=top_center,
            direction=direction,
            length=crown_height * rng.uniform(0.34, 0.68),
            width=crown_radius * rng.uniform(0.06, 0.12),
            bend=crown_radius * rng.uniform(0.02, 0.12),
        )
    return total_added


def _foliage_baobab_crown(
    bm,
    crown_position: Vector,
    crown_radius: float,
    crown_height: float,
    icosphere_subdivisions: int,
    rng: random.Random,
    smooth_shade: bool,
) -> int:
    """Sparse, high, broken leaf-card crown for baobab/savanna trees.

    The fat trunk does most of the visual work. The foliage is deliberately
    separated into small top leaf plates so it doesn't collapse into an oak.
    """
    total_added = 0
    n = rng.randint(7, 10)
    base_angle = rng.uniform(0, 2 * math.pi)
    for i in range(n):
        angle = base_angle + i * (2 * math.pi / n) + rng.uniform(-0.25, 0.25)
        direction = Vector((math.cos(angle), math.sin(angle), 0.0))
        radius = crown_radius * rng.uniform(0.35, 0.95)
        center = Vector((
            crown_position.x + direction.x * radius,
            crown_position.y + direction.y * radius,
            crown_position.z + crown_height * rng.uniform(0.62, 0.92),
        ))
        total_added += _add_leaf_card(
            bm,
            center=center,
            direction=direction,
            length=crown_radius * rng.uniform(0.42, 0.68),
            width=crown_radius * rng.uniform(0.16, 0.25),
            lift=crown_height * rng.uniform(0.01, 0.05),
            droop=crown_height * rng.uniform(0.02, 0.08),
        )
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
    "pine_cone":          _foliage_pine_cone,
    "round_ball":         _foliage_round_ball,
    "umbrella":           _foliage_umbrella,
    "crystal":            _foliage_crystal,
    "bush":               _foliage_bush,
    "layered_broadleaf":  _foliage_layered_broadleaf,
    "tiered_cones":       _foliage_tiered_cones,
    "leaf_cards":         _foliage_leaf_cards,
    "columnar":           _foliage_columnar,
    "windswept":          _foliage_windswept,
    "none":               _foliage_none,
    "weeping":            _foliage_weeping,
    "baobab_crown":       _foliage_baobab_crown,
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
        polygon_multiplier: float = 1.0,
        target_edge: float | None = None,
        trunk_segments: int | None = None,
        trunk_radius_base: float = 0.18,
        # Larger trunk_radius_top reduces the visible diameter
        # discontinuity where the thin trunk meets the wide foliage
        # blob — closes the "thin pole-into-balloon" floaty look.
        trunk_radius_top: float = 0.06,
        n_branch_layers: int = 6,
        branches_per_layer: tuple[int, int] = (3, 5),
        branch_length: tuple[float, float] = (0.7, 1.6),
        branch_droop: tuple[float, float] = (0.10, 0.55),
        branch_taper: float = 0.5,
        branch_lower_z_fraction: float | None = None,
        crown_z_fraction: float = 0.45,
        # Default archetype is pine_cone — most tree-like silhouette
        # for a generic forest scatter. Callers wanting deliberate
        # variety pass `foliage_archetype="tiered_cones"` /
        # "leaf_cards" / "columnar" / "windswept" / "weeping" /
        # "baobab_crown" / "none" / "umbrella" / "bush" / "crystal".
        foliage_archetype: str = "tiered_cones",
        foliage_layers: int = 4,
        foliage_radius: float = 1.6,
        foliage_height: float = 3.0,
        # Subdivision=2 → 320 polys/icosphere; matters for smooth
        # shading. With smooth_foliage=False (the default since
        # 2026-04-28) flat shading is the look, so 1 is also fine
        # but 2 keeps the silhouette curve cleaner.
        foliage_icosphere_subdivisions: int | None = None,
        # smooth_foliage=False is the canonical Maquette material — the
        # flat-shaded angular crystal-style look applied uniformly across
        # archetypes. Pass True for the smoother Sable/Genshin-pack feel
        # on a specific tree.
        smooth_foliage: bool = False,
        target_polys: int | None = None,
        trunk_color: str | None = "rock_shadow",
        palette_color: str | None = "foliage_pine",
        coarse: bool = False,
        **_unused_kwargs,
    ):
        # v5-3: route through the shared compat helper so the stderr warning
        # is uniformly formatted and the sidecar audit records the ignored
        # kwargs alongside the build artifacts.
        from infinigen.maquette.factory_kwargs_compat import accept_unused_kwargs
        accept_unused_kwargs("NativeLowPolyTreeFactory", _unused_kwargs)
        super().__init__(factory_seed, coarse=coarse)
        if archetype != "pine":
            # Lenient fallback — only 'pine' is implemented but Sonnet
            # may pick 'oak' / 'birch' / etc. Substitute and warn.
            import sys
            print(
                f"[archetype] WARN: unsupported archetype {archetype!r}; "
                f"falling back to 'pine' (only implemented archetype).",
                file=sys.stderr,
            )
            archetype = "pine"
        self.archetype = archetype
        if trunk_archetype not in _TRUNK_ARCHETYPES:
            # Lenient fallback rather than crash. Sonnet has been
            # observed to hallucinate plausible-sounding archetype
            # names despite the factories_guide brief listing the
            # valid set; killing a 6-minute build over a one-line
            # archetype typo wastes a generation. Substitute the
            # canonical default and warn to stderr.
            import sys
            print(
                f"[trunk_archetype] WARN: unknown trunk_archetype "
                f"{trunk_archetype!r}; falling back to {_TRUNK_ARCHETYPES[0]!r}. "
                f"Valid: {_TRUNK_ARCHETYPES}",
                file=sys.stderr,
            )
            trunk_archetype = _TRUNK_ARCHETYPES[0]
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
            # Lenient fallback rather than crash — see other archetype
            # validators in this package for the rationale.
            import sys
            _fallback = next(iter(_FOLIAGE_BUILDERS))
            print(
                f"[foliage_archetype] WARN: unknown foliage_archetype "
                f"{foliage_archetype!r}; falling back to {_fallback!r}. "
                f"Valid: {list(_FOLIAGE_BUILDERS)}",
                file=sys.stderr,
            )
            foliage_archetype = _fallback
        self.foliage_archetype = foliage_archetype
        self.foliage_layers = foliage_layers
        self.foliage_radius = foliage_radius
        self.foliage_height = foliage_height
        # Bbox-derive trunk_segments + foliage subdivisions if caller didn't
        # pin them. The tree's overall bbox roughly = (foliage_radius*2,
        # foliage_radius*2, trunk_height + foliage_height/2).
        edge = (
            float(target_edge) if target_edge is not None
            else target_edge_for_bbox(
                (self.foliage_radius * 2, self.foliage_radius * 2,
                 self.trunk_height + self.foliage_height * 0.5),
                polygon_multiplier=polygon_multiplier,
            )
        )
        self._density_edge = edge
        if trunk_segments is None:
            self.trunk_segments = max(3, n_along_axis(self.trunk_height, edge, min_n=4))
        else:
            self.trunk_segments = int(trunk_segments)
        if foliage_icosphere_subdivisions is None:
            # An icosphere of subdiv=0 has 20 faces and edge ≈ radius.
            # Each subdivision quarters the face count and halves the edge.
            self.foliage_icosphere_subdivisions = max(
                0,
                min(3, n_subdivisions(self.foliage_radius, edge, max_levels=3)),
            )
        else:
            self.foliage_icosphere_subdivisions = int(foliage_icosphere_subdivisions)
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

        # The trunk skeleton extends DEEP INTO the foliage volume (about
        # halfway up the foliage) so the trunk-foliage join feels
        # integrated, not "blob-floating-above-pole". The visible trunk
        # top inside foliage is hidden by the colored foliage material.
        # Was previously a much shallower overlap (min(0.6,
        # foliage_height * 0.3) ≈ 0.6 m); 0.5x foliage_height is enough
        # to bury the trunk top for any sensible foliage proportion.
        crown_z_base = self.trunk_height * self.crown_z_fraction
        trunk_skel_height = crown_z_base + min(self.foliage_height * 0.5, 1.5)

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
            branch_lower_z_fraction=min(
                0.99,
                (self.trunk_height * self.branch_lower_z_fraction)
                / max(trunk_skel_height, 1e-6),
            ),
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


class LowPolyTreeFactory(NativeLowPolyTreeFactory):
    """Compatibility wrapper for LLM-authored build scripts.

    The public factory bank exposes ``NativeLowPolyTreeFactory``, but generated
    scripts sometimes import the more obvious ``LowPolyTreeFactory`` from this
    module and pass ``species=...``. Keep that alias recoverable by mapping the
    legacy name to the native implementation and treating ``species`` as the
    native ``archetype`` hint when possible.
    """

    def __init__(self, factory_seed, species: str | None = None, **kwargs):
        if species and "archetype" not in kwargs:
            kwargs["archetype"] = "pine" if species == "pine" else species
        super().__init__(factory_seed, **kwargs)
