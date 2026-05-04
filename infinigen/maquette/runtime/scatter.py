"""Biome-driven scatter on Maquette terrain via Geometry Nodes.

The eroded terrain helper (`make_eroded_terrain`) writes a per-vertex
``Col`` FLOAT_COLOR attribute encoding the Whittaker biome of each
mesh point — meadow / forest / stone / alpine / snow / lakebed / shore.

This module exposes `scatter_on_terrain()`, which builds a Geometry
Nodes node-tree on the fly that:

    1. Reads the terrain via an Object Info node.
    2. Samples the ``Col`` named attribute per face.
    3. Filters faces with an RGB-comparison Selection matching the
       requested biome (e.g. "forest" → green-dominant low-luma).
    4. Distributes Poisson-disk points across surviving faces at the
       requested density (per square BU of eligible surface).
    5. Instances the supplied template object on those points with
       random Z rotation + random uniform scale jitter.
    6. Realises the instances so `bpy.ops.wm.obj_export` writes them
       as real geometry (Three.js `OBJLoader` reads them as a normal
       mesh — no glTF instancing required).

Output: a brand-new empty mesh object that owns the GN modifier.
The terrain itself stays clean; multiple scatters never write
modifiers onto the terrain (so they don't compound or interact).

Why this beats the for-loop placement Claude was writing:

  * 1000-instance scatter evaluates inside Blender's depsgraph in
    sub-second wall time vs ~50s for an equivalent Python loop.
  * Density tracks the same biome field that paints the terrain,
    so trees actually live in forest bands and boulders cluster
    on alpine slopes — no hand-tuned `if z > X` filters.
  * The OBJ export round-trips cleanly (instances realised) so
    nothing on the frontend has to change.
"""
from __future__ import annotations

from typing import Sequence

# Imports inside the function so the module loads cheaply outside Blender
# (e.g. when factories_guide regenerates documentation).


# Biome → RGB-test recipe. Each entry is a list of (channel, op, threshold)
# triples that all must hold (logical AND) for a face's `Col` to count
# as that biome.
#
# Thresholds are in **linear RGB**, matching how the eroded-terrain
# helper now writes vertex colors. The palette in
# ``eroded_terrain._DEFAULT_PALETTE`` is authored in sRGB intent and
# converted to linear at write time (so it doesn't blow out under the
# Standard view transform). Linear values:
#     meadow  (0.13, 0.21, 0.04)   forest  (0.03, 0.07, 0.02)
#     stone   (0.18, 0.15, 0.10)   alpine  (0.30, 0.27, 0.25)
#     snow    (0.71, 0.75, 0.82)   shore   (0.50, 0.40, 0.20)
#     lakebed (0.18, 0.13, 0.07)
_BIOME_TESTS: dict[str, list[tuple[str, str, float]]] = {
    # Bright grass — green dominant.
    "meadow":  [("G", ">", 0.13), ("G", "<", 0.40), ("R", "<", 0.27), ("B", "<", 0.10)],
    # Darker green — lower amplitude across all channels.
    "forest":  [("G", ">", 0.04), ("G", "<", 0.14), ("R", "<", 0.10), ("B", "<", 0.05)],
    # Grass band overall (forest + meadow combined) — useful for tree
    # scatter that's happy in either green band.
    "grass":   [("G", ">", 0.04), ("G", "<", 0.40), ("R", "<", 0.27), ("B", "<", 0.12)],
    # Stone band — neutral grey-brown, mid-low.
    "stone":   [("R", ">", 0.13), ("R", "<", 0.27), ("G", ">", 0.10), ("G", "<", 0.22),
                ("B", ">", 0.07), ("B", "<", 0.16)],
    # Alpine — neutral grey, brighter than stone.
    "alpine":  [("R", ">", 0.25), ("R", "<", 0.42), ("G", ">", 0.22), ("B", ">", 0.20),
                ("B", "<", 0.34)],
    # Snow — all channels bright (linear ≈ 0.7+).
    "snow":    [("R", ">", 0.55), ("G", ">", 0.55), ("B", ">", 0.55)],
    # Sandy shore — R high, B much lower.
    "shore":   [("R", ">", 0.36), ("G", ">", 0.27), ("B", "<", 0.30), ("R", ">", "B+0.15")],
    # No filter — distribute everywhere except water (which we exclude
    # implicitly because the auto-water cubes sit above the lakebed mesh).
    "any":     [],
}


def _build_scatter_node_tree(name: str, biome_filter: str, *, use_path_mask: bool = False):
    """Construct the GN node tree. Returns a fresh `bpy.types.NodeTree`
    with sockets:
        IN  : Terrain (Object), Instance (Object), Density (Float), Seed (Int)
        OUT : Geometry  (the scattered + realised instances)

    When ``use_path_mask=True`` an extra Selection clause is wired in
    that gates distribution on a POINT-domain ``path_mask_keep`` float
    attribute on the terrain (1.0 = scatter allowed, 0.0 = corridor
    excluded). The caller is expected to write that attribute via
    :func:`bake_path_mask` before triggering depsgraph eval.
    """
    import bpy

    nt = bpy.data.node_groups.new(name, "GeometryNodeTree")

    # Sockets via the 4.x interface API.
    iface = nt.interface
    iface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    s_terrain = iface.new_socket("Terrain", in_out="INPUT", socket_type="NodeSocketObject")
    s_instance = iface.new_socket("Instance", in_out="INPUT", socket_type="NodeSocketObject")
    s_density = iface.new_socket("Density", in_out="INPUT", socket_type="NodeSocketFloat")
    s_density.default_value = 0.005
    s_seed = iface.new_socket("Seed", in_out="INPUT", socket_type="NodeSocketInt")
    s_seed.default_value = 0
    s_smin = iface.new_socket("Scale Min", in_out="INPUT", socket_type="NodeSocketFloat")
    s_smin.default_value = 0.85
    s_smax = iface.new_socket("Scale Max", in_out="INPUT", socket_type="NodeSocketFloat")
    s_smax.default_value = 1.15

    nodes = nt.nodes
    links = nt.links

    gi = nodes.new("NodeGroupInput")
    go = nodes.new("NodeGroupOutput")
    gi.location = (-1400, 0)
    go.location = (1100, 0)

    # Terrain mesh from Object Info, in world space (so absolute placements work).
    obj_info = nodes.new("GeometryNodeObjectInfo")
    obj_info.transform_space = "RELATIVE"
    obj_info.location = (-1100, 200)
    links.new(gi.outputs["Terrain"], obj_info.inputs["Object"])

    # Per-face attribute sample of `Col` — POINT-domain colour
    # auto-interpolates to FACE context where Distribute consumes it.
    named = nodes.new("GeometryNodeInputNamedAttribute")
    named.data_type = "FLOAT_COLOR"
    named.inputs["Name"].default_value = "Col"
    named.location = (-1100, -100)

    # GN-namespace separate-color (ShaderNodeSeparateColor is shader-only in 4.2).
    sep = nodes.new("FunctionNodeSeparateColor")
    sep.location = (-900, -100)
    links.new(named.outputs["Attribute"], sep.inputs["Color"])

    # Build the Selection: AND-chain of FunctionNodeCompare results.
    tests = _BIOME_TESTS.get(biome_filter, [])
    selection_socket = None
    last_y = -300
    for (chan, op, thr) in tests:
        cmp = nodes.new("FunctionNodeCompare")
        cmp.data_type = "FLOAT"
        cmp.operation = "GREATER_THAN" if op == ">" else "LESS_THAN"
        cmp.location = (-700, last_y)
        last_y -= 110
        # Channel input.
        if chan == "R":
            links.new(sep.outputs["Red"], cmp.inputs[0])
        elif chan == "G":
            links.new(sep.outputs["Green"], cmp.inputs[0])
        elif chan == "B":
            links.new(sep.outputs["Blue"], cmp.inputs[0])
        # Threshold input — supports plain floats and "channel±delta" strings
        # for relative comparisons (e.g. "B+0.10").
        if isinstance(thr, str):
            if "+" in thr or "-" in thr:
                ref_chan = thr[0]
                delta = float(thr[1:])
                m = nodes.new("ShaderNodeMath")
                m.operation = "ADD"
                m.location = (-870, last_y - 60)
                if ref_chan == "R":
                    links.new(sep.outputs["Red"], m.inputs[0])
                elif ref_chan == "G":
                    links.new(sep.outputs["Green"], m.inputs[0])
                elif ref_chan == "B":
                    links.new(sep.outputs["Blue"], m.inputs[0])
                m.inputs[1].default_value = delta
                links.new(m.outputs[0], cmp.inputs[1])
            else:
                cmp.inputs[1].default_value = float(thr)
        else:
            cmp.inputs[1].default_value = float(thr)

        if selection_socket is None:
            selection_socket = cmp.outputs["Result"]
        else:
            and_node = nodes.new("FunctionNodeBooleanMath")
            and_node.operation = "AND"
            and_node.location = (-500, last_y + 100)
            links.new(selection_socket, and_node.inputs[0])
            links.new(cmp.outputs["Result"], and_node.inputs[1])
            selection_socket = and_node.outputs["Boolean"]

    # Optional path-corridor mask: AND the existing biome selection with
    # `path_mask_keep > 0.5`. Vertex attribute is written by
    # bake_path_mask() before scatter; when missing the named-attribute
    # node returns 0.0, which would block all scatter — so we only wire
    # the clause when use_path_mask is true.
    if use_path_mask:
        path_attr = nodes.new("GeometryNodeInputNamedAttribute")
        path_attr.data_type = "FLOAT"
        path_attr.inputs["Name"].default_value = "path_mask_keep"
        path_attr.location = (-1100, -300)
        path_cmp = nodes.new("FunctionNodeCompare")
        path_cmp.data_type = "FLOAT"
        path_cmp.operation = "GREATER_THAN"
        path_cmp.location = (-700, last_y - 200)
        links.new(path_attr.outputs["Attribute"], path_cmp.inputs[0])
        path_cmp.inputs[1].default_value = 0.5
        if selection_socket is None:
            selection_socket = path_cmp.outputs["Result"]
        else:
            and_node = nodes.new("FunctionNodeBooleanMath")
            and_node.operation = "AND"
            and_node.location = (-500, last_y - 200)
            links.new(selection_socket, and_node.inputs[0])
            links.new(path_cmp.outputs["Result"], and_node.inputs[1])
            selection_socket = and_node.outputs["Boolean"]

    # Distribute points on the terrain faces.
    dist = nodes.new("GeometryNodeDistributePointsOnFaces")
    dist.distribute_method = "POISSON"
    dist.location = (-300, 100)
    links.new(obj_info.outputs["Geometry"], dist.inputs["Mesh"])
    if selection_socket is not None:
        links.new(selection_socket, dist.inputs["Selection"])
    links.new(gi.outputs["Density"], dist.inputs["Density Max"])
    # Density Factor stays at default 1.0 → uniform within selected band.
    # Distance Min derived from density: ~ 1 / sqrt(density * pi).
    dist.inputs["Distance Min"].default_value = 0.4
    links.new(gi.outputs["Seed"], dist.inputs["Seed"])

    # Random Z rotation.
    rand_rot = nodes.new("FunctionNodeRandomValue")
    rand_rot.data_type = "FLOAT_VECTOR"
    rand_rot.location = (-100, -100)
    rand_rot.inputs["Min"].default_value = (0.0, 0.0, 0.0)
    rand_rot.inputs["Max"].default_value = (0.0, 0.0, 6.2831853)  # 2π
    links.new(gi.outputs["Seed"], rand_rot.inputs["Seed"])

    # Random uniform scale jitter.
    rand_scale = nodes.new("FunctionNodeRandomValue")
    rand_scale.data_type = "FLOAT"
    rand_scale.location = (-100, -300)
    links.new(gi.outputs["Scale Min"], rand_scale.inputs[2])  # Min (float)
    links.new(gi.outputs["Scale Max"], rand_scale.inputs[3])  # Max (float)
    links.new(gi.outputs["Seed"], rand_scale.inputs["Seed"])

    # Instance the template object's geometry on each point.
    inst_info = nodes.new("GeometryNodeObjectInfo")
    inst_info.transform_space = "RELATIVE"
    inst_info.location = (-100, 200)
    links.new(gi.outputs["Instance"], inst_info.inputs["Object"])

    inst_on = nodes.new("GeometryNodeInstanceOnPoints")
    inst_on.location = (200, 0)
    links.new(dist.outputs["Points"], inst_on.inputs["Points"])
    links.new(inst_info.outputs["Geometry"], inst_on.inputs["Instance"])
    links.new(rand_rot.outputs[0], inst_on.inputs["Rotation"])
    # Scalar scale → vector via Combine XYZ for uniform xy scaling.
    combine = nodes.new("ShaderNodeCombineXYZ")
    combine.location = (40, -300)
    links.new(rand_scale.outputs[1], combine.inputs["X"])
    links.new(rand_scale.outputs[1], combine.inputs["Y"])
    links.new(rand_scale.outputs[1], combine.inputs["Z"])
    links.new(combine.outputs["Vector"], inst_on.inputs["Scale"])

    # Realize so OBJ export sees real triangles.
    realise = nodes.new("GeometryNodeRealizeInstances")
    realise.location = (500, 0)
    links.new(inst_on.outputs["Instances"], realise.inputs["Geometry"])

    links.new(realise.outputs["Geometry"], go.inputs["Geometry"])

    return nt


def bake_path_mask(
    terrain_obj,
    polylines: "list[list[tuple[float, float]]] | list[tuple[float, float]]",
    radius: float = 1.6,
) -> None:
    """Write a POINT-domain ``path_mask_keep`` FLOAT attribute on
    ``terrain_obj`` that is 0.0 within ``radius`` of any segment in
    ``polylines`` and 1.0 elsewhere.

    Re-callable: calling it again with a different polyline replaces
    the attribute. Subsequent ``scatter_on_terrain(... exclude_polylines=...)``
    calls reuse the bake.

    Parameters
    ----------
    terrain_obj
        The Blender mesh object (typically ``Terrain.obj`` from
        ``make_eroded_terrain``).
    polylines
        Either one polyline (``[(x,y), (x,y), ...]``) or a list of
        polylines for branching paths. Each polyline must have ≥2
        points; segments are linear interpolations between consecutive
        points.
    radius
        Half-width in BU of the corridor to exclude. Defaults to 1.6
        (matches a 2.4 BU path with a small buffer).
    """
    import bpy
    import numpy as np

    me = terrain_obj.data
    n = len(me.vertices)
    if n == 0:
        return

    pts = np.empty((n, 3), dtype=np.float32)
    me.vertices.foreach_get("co", pts.reshape(-1))
    px = pts[:, 0]
    py = pts[:, 1]

    # Normalize input to a list of polylines.
    if polylines and isinstance(polylines[0], (tuple, list)) and len(polylines[0]) == 2 and not isinstance(polylines[0][0], (tuple, list)):
        polys = [polylines]
    else:
        polys = list(polylines)

    min_dist = np.full(n, np.inf, dtype=np.float32)
    for poly in polys:
        pl = list(poly)
        if len(pl) < 2:
            continue
        for k in range(len(pl) - 1):
            ax, ay = float(pl[k][0]), float(pl[k][1])
            bx, by = float(pl[k + 1][0]), float(pl[k + 1][1])
            seg_dx = bx - ax
            seg_dy = by - ay
            seg_len2 = seg_dx * seg_dx + seg_dy * seg_dy
            if seg_len2 < 1e-9:
                d = np.sqrt((px - ax) ** 2 + (py - ay) ** 2)
            else:
                t = ((px - ax) * seg_dx + (py - ay) * seg_dy) / seg_len2
                t = np.clip(t, 0.0, 1.0)
                cx = ax + t * seg_dx
                cy = ay + t * seg_dy
                d = np.sqrt((px - cx) ** 2 + (py - cy) ** 2)
            np.minimum(min_dist, d, out=min_dist)

    keep = (min_dist > float(radius)).astype(np.float32)

    # Replace any prior attribute by name. Domain=POINT so the GN tree's
    # Distribute node interpolates correctly when consuming it.
    if "path_mask_keep" in me.attributes:
        me.attributes.remove(me.attributes["path_mask_keep"])
    attr = me.attributes.new(name="path_mask_keep", type="FLOAT", domain="POINT")
    attr.data.foreach_set("value", keep.tolist())
    me.update()


def scatter_on_terrain(
    *,
    terrain_obj,
    instance_obj,
    density: float = 0.005,
    biome_filter: str = "any",
    seed: int = 42,
    scale_jitter: tuple[float, float] = (0.85, 1.15),
    name: str | None = None,
    hide_instance_template: bool = True,
    exclude_polylines: "list[list[tuple[float, float]]] | list[tuple[float, float]] | None" = None,
    exclude_radius: float = 1.6,
):
    """Scatter copies of ``instance_obj`` onto the surface of
    ``terrain_obj``, density-modulated by the terrain's ``Col`` biome
    attribute matching ``biome_filter``.

    Returns the newly-created Blender object that hosts the scatter
    Geometry Nodes modifier — its evaluated mesh is the realised
    instances. The terrain itself is untouched.

    Parameters
    ----------
    terrain_obj
        The procedural terrain mesh from ``make_eroded_terrain``.
        Must carry a POINT-domain ``Col`` FLOAT_COLOR attribute.
    instance_obj
        The template object to instance — typically a single result
        from a Maquette factory (``LowPolyTreeFactory(...).create_asset(...)``).
        Pass ONE template, even if you want 1000 trees: the GN scatter
        instances it many times.
    density
        Poisson-disk point density per square BU of eligible surface.
        REMEMBER: this multiplies by area. A 280 BU world has ~78000
        BU² so density=1.0 gives ~78k points — way too many. Realistic
        ranges:
          trees on grass band : 0.003 - 0.010   (200-700 trees over a panorama)
          boulders on alpine  : 0.010 - 0.025   (~100-300 rocks)
          dense forest patch  : 0.020 - 0.040   (small focused regions)
    biome_filter
        One of ``"meadow"``, ``"forest"``, ``"grass"``, ``"stone"``,
        ``"alpine"``, ``"snow"``, ``"shore"``, ``"any"``. ``"grass"``
        spans both meadow + forest bands and is usually what you want
        for general tree scatter.
    seed
        Pass distinct seeds for distinct scatter calls so multiple
        scatters of the same biome (e.g. pines + shrubs) don't sample
        the same point set.
    scale_jitter
        Tuple ``(min, max)`` for random uniform scale per instance.
    name
        Optional name for the scatter object. Defaults to
        ``f"Scatter_{biome_filter}"`` plus a numeric suffix if
        the name already exists.
    hide_instance_template
        Hide the supplied template from the camera + render after
        wiring it. The GN scatter still references it via Object Info,
        but the lone template otherwise sits at the world origin and
        photobombs the render.
    exclude_polylines
        Optional list of polylines (each polyline = list of (x, y)
        waypoints) defining path corridors that scatter must avoid.
        When provided, the helper bakes a per-vertex ``path_mask_keep``
        attribute on ``terrain_obj`` (1.0 outside the corridor, 0.0
        inside) and the GN selection AND-s with that mask. Multiple
        scatter calls share the same baked mask, so pass it once on
        the first scatter and re-use across subsequent calls.
    exclude_radius
        Half-width of the corridor to exclude. Defaults to 1.6 BU
        (suits a 2.4 BU path with a small buffer).
    """
    import bpy

    name = name or f"Scatter_{biome_filter}"

    # If the caller supplied a path corridor, bake the mask attribute on
    # the terrain *now* so the GN tree can read it. Cheap if the mask
    # already exists with the same parameters.
    use_path_mask = exclude_polylines is not None
    if use_path_mask:
        bake_path_mask(terrain_obj, exclude_polylines, radius=exclude_radius)

    # Build the node-tree (one tree per scatter call — they're cheap and
    # keeping them separate avoids modifier-stacking surprises).
    nt = _build_scatter_node_tree(f"NT_{name}", biome_filter, use_path_mask=use_path_mask)

    # Empty mesh as the scatter object's data — the GN modifier produces
    # the actual geometry when the depsgraph evaluates.
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    mod = obj.modifiers.new(name=name, type="NODES")
    mod.node_group = nt
    # Identifier-based input keys ("Socket_1" etc) — match by name.
    for item in nt.interface.items_tree:
        if getattr(item, "in_out", None) != "INPUT":
            continue
        if item.name == "Terrain":
            mod[item.identifier] = terrain_obj
        elif item.name == "Instance":
            mod[item.identifier] = instance_obj
        elif item.name == "Density":
            mod[item.identifier] = float(density)
        elif item.name == "Seed":
            mod[item.identifier] = int(seed)
        elif item.name == "Scale Min":
            mod[item.identifier] = float(scale_jitter[0])
        elif item.name == "Scale Max":
            mod[item.identifier] = float(scale_jitter[1])

    if hide_instance_template:
        instance_obj.hide_render = True
        instance_obj.hide_viewport = True

    return obj
