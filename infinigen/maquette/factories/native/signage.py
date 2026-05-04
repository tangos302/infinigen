"""LowPolySignageFactory — painted wooden storefront sign.

Requested 2026-04-28 (Wild West town). Storefront / saloon / sheriff
sign — a flat painted board mounted to a post or hung from a bracket.
Distinctive frontier-town silhouette; also fits medieval inns and
shop fronts.

Archetypes:
  hanging_shingle — small rectangular board hanging from a wall
                     bracket arm, swings off to the side
  wall_plank      — wider plank mounted flat against a building face,
                     two posts framing it (free-standing variant)
  free_standing   — two short posts + a horizontal sign board between
                     them at chest height (notice board / shop sign)

Material slots:
  slot 0 = posts / bracket / frame  (default `wood`)
  slot 1 = sign board face          (default `stucco`)
  slot 2 = paint accent             (default `accent_red`)
"""

from __future__ import annotations

import bmesh
import bpy

from infinigen.core.placement.factory import AssetFactory

from ...materials import apply_palette_slots


_SIGNAGE_ARCHETYPES = ("hanging_shingle", "wall_plank", "free_standing")


_ARCHETYPE_DEFAULTS = {
    "hanging_shingle": dict(
        post_height=2.40, post_size=0.10,
        bracket_length=0.75, bracket_thickness=0.06,
        board_w=0.95, board_h=0.55, board_thickness=0.05,
        accent_w_frac=0.85, accent_h_frac=0.55,
        wood_color="wood", board_color="stucco", accent_color="accent_red",
        has_post=True,
    ),
    "wall_plank": dict(
        post_height=1.6, post_size=0.10,
        bracket_length=0.0, bracket_thickness=0.05,
        board_w=2.20, board_h=0.65, board_thickness=0.07,
        accent_w_frac=0.90, accent_h_frac=0.50,
        wood_color="wood", board_color="stucco", accent_color="accent_red",
        has_post=True,
    ),
    "free_standing": dict(
        post_height=1.6, post_size=0.09,
        bracket_length=0.0, bracket_thickness=0.05,
        board_w=1.20, board_h=0.45, board_thickness=0.05,
        accent_w_frac=0.92, accent_h_frac=0.55,
        wood_color="wood", board_color="stucco", accent_color="accent_red",
        has_post=True,
    ),
}


def _bm_face_count(bm) -> int:
    return len(bm.faces)


def _add_box(bm, slot_ranges, slot, cx, cy, cz, sx, sy, sz):
    start = _bm_face_count(bm)
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    b00 = bm.verts.new((cx - hx, cy - hy, cz - hz))
    b10 = bm.verts.new((cx + hx, cy - hy, cz - hz))
    b11 = bm.verts.new((cx + hx, cy + hy, cz - hz))
    b01 = bm.verts.new((cx - hx, cy + hy, cz - hz))
    t00 = bm.verts.new((cx - hx, cy - hy, cz + hz))
    t10 = bm.verts.new((cx + hx, cy - hy, cz + hz))
    t11 = bm.verts.new((cx + hx, cy + hy, cz + hz))
    t01 = bm.verts.new((cx - hx, cy + hy, cz + hz))
    bm.verts.ensure_lookup_table()
    bm.faces.new((b00, b10, t10, t00))
    bm.faces.new((b10, b11, t11, t10))
    bm.faces.new((b11, b01, t01, t11))
    bm.faces.new((b01, b00, t00, t01))
    bm.faces.new((t00, t10, t11, t01))
    bm.faces.new((b00, b01, b11, b10))
    end = _bm_face_count(bm)
    slot_ranges.append((start, end, slot))


class LowPolySignageFactory(AssetFactory):
    """A painted storefront / shop / inn sign — three archetypes.

    Constructor knobs:

        factory_seed
        signage_archetype : str = "hanging_shingle" | "wall_plank"
                                  | "free_standing"
        post_height, post_size : float
        board_w, board_h, board_thickness : float
        wood_color, board_color, accent_color : palette keys
    """

    def __init__(
        self,
        factory_seed,
        signage_archetype: str = "hanging_shingle",
        post_height: float | None = None,
        post_size: float | None = None,
        board_w: float | None = None,
        board_h: float | None = None,
        board_thickness: float | None = None,
        bracket_length: float | None = None,
        bracket_thickness: float | None = None,
        wood_color: str | None = None,
        board_color: str | None = None,
        accent_color: str | None = None,
        coarse: bool = False,
    ):
        super().__init__(factory_seed, coarse=coarse)
        if signage_archetype not in _SIGNAGE_ARCHETYPES:
            raise ValueError(
                f"unknown signage_archetype {signage_archetype!r}; "
                f"valid: {_SIGNAGE_ARCHETYPES}"
            )
        d = _ARCHETYPE_DEFAULTS[signage_archetype]
        self.signage_archetype = signage_archetype
        self.post_height = float(post_height if post_height is not None else d["post_height"])
        self.post_size = float(post_size if post_size is not None else d["post_size"])
        self.board_w = float(board_w if board_w is not None else d["board_w"])
        self.board_h = float(board_h if board_h is not None else d["board_h"])
        self.board_thickness = float(
            board_thickness if board_thickness is not None else d["board_thickness"]
        )
        self.bracket_length = float(
            bracket_length if bracket_length is not None else d["bracket_length"]
        )
        self.bracket_thickness = float(
            bracket_thickness if bracket_thickness is not None else d["bracket_thickness"]
        )
        self.accent_w_frac = float(d["accent_w_frac"])
        self.accent_h_frac = float(d["accent_h_frac"])
        self.has_post = bool(d["has_post"])
        self.wood_color = wood_color or d["wood_color"]
        self.board_color = board_color or d["board_color"]
        self.accent_color = accent_color or d["accent_color"]

    def create_placeholder(self, **kwargs) -> bpy.types.Object:
        ph = bpy.data.objects.new(
            f"LowPolySignage({self.factory_seed})_placeholder", None
        )
        bpy.context.scene.collection.objects.link(ph)
        return ph

    def create_asset(self, placeholder=None, **kwargs) -> bpy.types.Object:
        return self._build()

    def _build(self) -> bpy.types.Object:
        bm = bmesh.new()
        slot_ranges: list[tuple[int, int, int]] = []

        if self.signage_archetype == "hanging_shingle":
            # Single tall post + horizontal bracket arm + dangling board
            _add_box(
                bm, slot_ranges, 0,
                0.0, 0.0, self.post_height / 2,
                self.post_size, self.post_size, self.post_height,
            )
            # Bracket arm extending in +Y
            arm_z = self.post_height - self.bracket_thickness
            _add_box(
                bm, slot_ranges, 0,
                0.0, self.bracket_length / 2, arm_z,
                self.bracket_thickness, self.bracket_length, self.bracket_thickness,
            )
            # Vertical chains/links from arm tip down to board
            link_z = arm_z - 0.10
            _add_box(
                bm, slot_ranges, 0,
                0.0, self.bracket_length - 0.05, link_z,
                self.bracket_thickness * 0.6, self.bracket_thickness * 0.6, 0.20,
            )
            # Board
            board_cz = arm_z - 0.20 - self.board_h / 2
            board_cy = self.bracket_length - 0.05
            _add_box(
                bm, slot_ranges, 1,
                0.0, board_cy, board_cz,
                self.board_w, self.board_thickness, self.board_h,
            )
            # Painted accent (slightly forward)
            _add_box(
                bm, slot_ranges, 2,
                0.0, board_cy - self.board_thickness * 0.5, board_cz,
                self.board_w * self.accent_w_frac,
                self.board_thickness * 0.2,
                self.board_h * self.accent_h_frac,
            )

        elif self.signage_archetype == "free_standing":
            # Two posts framing the board
            half_w = self.board_w / 2 + self.post_size
            for sign in (-1, 1):
                _add_box(
                    bm, slot_ranges, 0,
                    sign * half_w, 0.0, self.post_height / 2,
                    self.post_size, self.post_size, self.post_height,
                )
            # Board between posts at upper half
            board_cz = self.post_height * 0.65
            _add_box(
                bm, slot_ranges, 1,
                0.0, 0.0, board_cz,
                self.board_w, self.board_thickness, self.board_h,
            )
            # Painted accent
            _add_box(
                bm, slot_ranges, 2,
                0.0, -self.board_thickness * 0.5, board_cz,
                self.board_w * self.accent_w_frac,
                self.board_thickness * 0.2,
                self.board_h * self.accent_h_frac,
            )

        else:  # wall_plank
            # Two posts at bottom corners, big horizontal board on top
            half_w = self.board_w / 2 - self.post_size
            for sign in (-1, 1):
                _add_box(
                    bm, slot_ranges, 0,
                    sign * half_w, 0.0, self.post_height / 2,
                    self.post_size, self.post_size, self.post_height,
                )
            # Board across the top
            board_cz = self.post_height + self.board_h / 2
            _add_box(
                bm, slot_ranges, 1,
                0.0, 0.0, board_cz,
                self.board_w, self.board_thickness, self.board_h,
            )
            # Painted accent
            _add_box(
                bm, slot_ranges, 2,
                0.0, -self.board_thickness * 0.5, board_cz,
                self.board_w * self.accent_w_frac,
                self.board_thickness * 0.2,
                self.board_h * self.accent_h_frac,
            )

        me = bpy.data.meshes.new(f"LowPolySignage({self.factory_seed})_Mesh")
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(
            f"LowPolySignage({self.factory_seed})", me,
        )
        bpy.context.scene.collection.objects.link(obj)
        while len(obj.data.materials) < 3:
            obj.data.materials.append(None)
        for start, end, slot in slot_ranges:
            for i in range(start, end):
                obj.data.polygons[i].material_index = slot
        for p in obj.data.polygons:
            p.use_smooth = False

        apply_palette_slots(obj, [self.wood_color, self.board_color, self.accent_color])
        return obj
