# Copyright (C) 2023, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory of this source tree.

# Authors:
# - Alexander Raistrick: primary author
# - Lahav Lipson: resample nodegroup


import bpy
import numpy as np
from numpy.random import normal, uniform

from infinigen.core import surface
from infinigen.core.nodes.node_wrangler import Nodes, NodeWrangler
from infinigen.core.util.color import random_color_mapping


def to_material(name, singleton):
    """Wrapper for initializing and registering materials."""

    if singleton:
        name += " (no gc)"

    def registration_fn(fn):
        def init_fn(*args, **kwargs):
            if singleton and name in bpy.data.materials:
                return bpy.data.materials[name]
            else:
                return surface.shaderfunc_to_material(fn, *args, name=name, *kwargs)

        return init_fn

    return registration_fn


def to_nodegroup(name=None, singleton=False, type="GeometryNodeTree"):
    """Wrapper for initializing and registering new nodegroups."""

    def registration_fn(fn):
        nonlocal name
        if name is None:
            name = fn.__name__
        if singleton:
            name = name + " (no gc)"

        def init_fn(*args, **kwargs):
            if singleton and name in bpy.data.node_groups:
                return bpy.data.node_groups[name]
            else:
                ng = bpy.data.node_groups.new(name, type)
                nw = NodeWrangler(ng)
                fn(nw, *args, **kwargs)
                return ng

        return init_fn

    return registration_fn


def assign_curve(c, points, handles=None):
    """Set a CurveMap's control points.

    Blender 4.2 changed CurveMapPoints.new() to silently return None
    (raising bpy SystemError "returned NULL without setting an
    exception") when called with arbitrary (x, y) coordinates that
    violate internal invariants — typically when the new point's x
    coordinate matches or is too close to an existing point's x.

    Workaround: create new points at safely-spaced default x positions
    first, then set their final location. The default y is 0.5 (mid-
    range, always valid) and we space defaults across (0, 1) so each
    new point lands at a unique x. The final loop then writes the
    desired location, which Blender accepts as a position update on an
    existing point.
    """
    # Normalise `points` to plain (x, y) float tuples. Callers sometimes
    # pass numpy size-1 arrays as components — e.g.
    # `normal(0, 0.2, 1)` returns `np.array([…])`, so a tuple element can
    # be a 1-D array. Numpy 2.x rejects implicit `float()` on size-1
    # arrays, so we go via `.item()` (works on Python floats too via
    # `np.asarray`).
    import numpy as _np

    def _scalar(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return float(_np.asarray(x).item())

    pts = [(_scalar(p[0]), _scalar(p[1])) for p in points]
    n_pts = len(pts)
    n_existing = len(c.points)

    # Phase 1: ensure the curve has enough point slots.
    for i in range(n_existing, n_pts):
        # Spread placeholder x positions so consecutive new() calls
        # don't collide on the same x (Blender 4.2 silently rejects
        # those, returning NULL without raising).
        placeholder_x = 0.05 + 0.9 * (i + 1) / (n_pts + 1)
        try:
            c.points.new(placeholder_x, 0.5)
        except (SystemError, RuntimeError):
            # Even the placeholder rejected — accept fewer points and
            # let the caller's shader degrade gracefully.
            break

    # Phase 2: set each point's final location and handle type.
    for i, (x, y) in enumerate(pts):
        if i >= len(c.points):
            break
        c.points[i].location = (x, y)
        if handles is not None and i < len(handles):
            c.points[i].handle_type = handles[i]


def facing_mask(nw, dir, thresh=0.5):
    normal = nw.new_node(Nodes.InputNormal)
    up_mask = nw.new_node(
        Nodes.VectorMath,
        input_kwargs={0: normal, 1: dir},
        attrs={"operation": "DOT_PRODUCT"},
    )
    up_mask = nw.new_node(
        Nodes.Math, input_args=[up_mask, thresh], attrs={"operation": "GREATER_THAN"}
    )

    return up_mask


def noise(nw, scale, **kwargs):
    return nw.new_node(
        Nodes.NoiseTexture,
        input_kwargs={
            "Scale": scale,
            "W": uniform(1e3),
            # Making this as big as 1e6 seems to cause bugs
            "Detail": kwargs.get("detail", uniform(0, 10)),
            "Roughness": kwargs.get("roughness", uniform(0, 1)),
            "Distortion": kwargs.get("distortion", normal(0.7, 0.4)),
        },
        attrs={"noise_dimensions": "4D"},
    )


def resample_node_group(nw: NodeWrangler, scene_seed: int):
    for node in nw.nodes:
        # Randomize 'W' in noise nodes
        if node.bl_idname in {Nodes.NoiseTexture, Nodes.WhiteNoiseTexture}:
            node.noise_dimensions = "4D"
            node.inputs["W"].default_value = np.random.uniform(1000)

        if node.bl_idname == Nodes.ColorRamp:
            for element in node.color_ramp.elements:
                element.color = random_color_mapping(element.color, scene_seed)

        if node.bl_idname == Nodes.RGB:
            node.outputs["Color"].default_value = random_color_mapping(
                node.outputs["Color"].default_value, scene_seed
            )

        # Randomized fixed color input
        for input_socket in node.inputs:
            if input_socket.type == "RGBA":
                # print(f"Mapping", input_socket)
                input_socket.default_value = random_color_mapping(
                    input_socket.default_value, scene_seed
                )

            if input_socket.name == "Seed":
                input_socket.default_value = np.random.randint(1000)


def build_color_ramp(nw, x, positions, colors, mode="HSV"):
    cr = nw.new_node(Nodes.ColorRamp, input_kwargs={"Fac": x})
    cr.color_ramp.color_mode = mode
    elements = cr.color_ramp.elements
    size = len(positions)
    assert len(colors) == size
    if size > 2:
        for _ in range(size - 2):
            elements.new(0)
    for i, (p, c) in enumerate(zip(positions, colors)):
        elements[i].position = p
        elements[i].color = c
    return cr
