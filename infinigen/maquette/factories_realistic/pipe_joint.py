"""RealisticPipeJointFactory — pipework joint primitive.

Re-implements the elbow-joint geometry from
`bl_ext.blender_org.extra_mesh_objects.add_mesh_pipe_joint` directly (the
addon buries it in an Operator's `execute()`; calling that needs the
right `bpy.context.mode` and a temp_override). The math is ~30 lines of
trig — three circular vertex loops with the middle one tilted.

Use for industrial / steampunk / sewer scenes: pipework against walls,
exposed plumbing, ventilation ducts.

Archetype mapping (the elbow's `angle` is the geometric knob):

    "elbow_45"  : 45° turn (gentle)
    "elbow_90"  : 90° turn (canonical)
    "elbow_135" : 135° turn (sharp)
    "any"       : random pick

License: derived from the GPL-2.0 elbow-joint operator.
"""

from __future__ import annotations

import math

import bpy
import numpy as np

from infinigen.core.placement.factory import AssetFactory
from infinigen.core.util.math import FixedSeed


_PIPE_ARCHETYPES = ("elbow_45", "elbow_90", "elbow_135", "any")

_ARCHETYPE_TO_ANGLE: dict[str, float] = {
    "elbow_45":  math.radians(45.0),
    "elbow_90":  math.radians(90.0),
    "elbow_135": math.radians(135.0),
}


def _make_elbow_mesh(
    radius: float,
    angle: float,
    div: int,
    start_length: float,
    end_length: float,
) -> tuple[list[list[float]], list[list[int]]]:
    """Return (verts, faces) for a pipe elbow joint.

    Replicates `add_mesh_pipe_joint.AddElbowJoint.execute` lines 190-235:
    three circular loops (start, deformed joint, end) connected by faces.
    """
    verts: list[list[float]] = []
    loop1: list[int] = []
    loop2: list[int] = []
    loop3: list[int] = []

    # Starting circle (at -start_length on Z axis).
    for v in range(div):
        a = v * (2.0 * math.pi / div)
        x, y = math.sin(a), math.cos(a)
        loop1.append(len(verts))
        verts.append([x * radius, y * radius, -start_length])

    # Deformed joint circle (Z slants by tan(angle/2)).
    for v in range(div):
        a = v * (2.0 * math.pi / div)
        x, y = math.sin(a), math.cos(a)
        z = x * math.tan(angle / 2.0)
        loop2.append(len(verts))
        verts.append([x * radius, y * radius, z * radius])

    # End circle, rotated and translated to align with the bend.
    base_end_x = -end_length * math.sin(angle)
    base_end_z = end_length * math.cos(angle)
    for v in range(div):
        a = v * (2.0 * math.pi / div)
        lx = math.sin(a) * radius
        ly = math.cos(a) * radius
        # Rotate the base circle by (pi/2 - angle) around Y.
        lz_r = lx * math.cos(math.pi / 2.0 - angle)
        lx_r = lx * math.sin(math.pi / 2.0 - angle)
        loop3.append(len(verts))
        verts.append([base_end_x + lx_r, ly, base_end_z + lz_r])

    faces: list[list[int]] = []
    for loop_a, loop_b in ((loop1, loop2), (loop2, loop3)):
        n = len(loop_a)
        for i in range(n):
            j = (i + 1) % n
            faces.append([loop_a[i], loop_a[j], loop_b[j], loop_b[i]])

    return verts, faces


class RealisticPipeJointFactory(AssetFactory):
    """Realistic pipe-elbow factory.

    Constructor knobs:

        factory_seed : int
        archetype : str = "elbow_90"
            One of: elbow_45 / elbow_90 / elbow_135 / any.
        radius : float = 0.15  (pipe radius, meters)
        div : int = 16  (vertex resolution per circular loop)
        leg_length : float = 0.6  (length of straight section before/after bend)
    """

    def __init__(
        self,
        factory_seed: int,
        archetype: str = "elbow_90",
        radius: float = 0.15,
        div: int = 16,
        leg_length: float = 0.6,
        coarse: bool = False,
    ):
        if archetype not in _PIPE_ARCHETYPES:
            raise ValueError(
                f"archetype={archetype!r} not in {_PIPE_ARCHETYPES}"
            )
        super().__init__(factory_seed, coarse=coarse)
        if archetype == "any":
            with FixedSeed(factory_seed):
                non_any = [a for a in _PIPE_ARCHETYPES if a != "any"]
                archetype = str(np.random.choice(non_any))
        self.archetype = archetype
        self.radius = radius
        self.div = div
        self.leg_length = leg_length

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        empty = bpy.data.objects.new("PipeJointPlaceholder", None)
        bpy.context.collection.objects.link(empty)
        return empty

    def create_asset(self, i: int = 0, placeholder=None, **params) -> bpy.types.Object:
        angle = _ARCHETYPE_TO_ANGLE[self.archetype]
        verts, faces = _make_elbow_mesh(
            radius=self.radius,
            angle=angle,
            div=self.div,
            start_length=self.leg_length,
            end_length=self.leg_length,
        )
        mesh = bpy.data.meshes.new(f"PipeJoint.{self.archetype}.{i}")
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(mesh.name, mesh)
        bpy.context.collection.objects.link(obj)
        return obj
