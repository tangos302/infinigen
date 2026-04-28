"""LowPolyTreeFactory — bare-trunk Firewatch silhouette.

Upstream `TreeFactory` builds the trunk skin AND a heavy
leaf/twig/fruit collection (`child_col`) that gets instanced onto
the tree skeleton during `create_asset` via the `add_tree_children`
geometry node. That foliage path is the bulk of Infinigen's tree
compute and produces million-poly trees.

Strategy (v0a):
  - Subclass GenericTreeFactory directly (NOT TreeFactory).
  - Re-run TreeFactory's procedural-choice phase (random_species,
    bark surface) so we still get its species variety, season
    selection, etc.
  - Pass `child_col=None` to GenericTreeFactory.__init__ so no
    leaf/twig/fruit collection is built — we never pay the foliage
    cost.
  - Override `create_asset` to override face_size (much larger),
    flat-shade the result, optionally apply a palette color.

Result: a low-poly trunk-and-branches mesh, faceted, optionally
tinted (e.g. `palette_color="rock_shadow"` for charred-bark or
`"foliage_pine"` for a pine green silhouette). Reads as a winter /
dead tree silhouette — exactly the tall slender Firewatch tree
shape minus its conical foliage clump.

Foliage clumps (v0b) can be added in a follow-up commit by
generating a simple icosphere-cluster collection and passing it as
`child_col` instead of None.
"""

from __future__ import annotations

import bpy
import numpy as np

from infinigen.assets.objects.trees import treeconfigs
from infinigen.assets.objects.trees.generate import (
    GenericTreeFactory,
    random_species,
)
from infinigen.core.tagging import tag_object
from infinigen.core.util import blender as butil
from infinigen.core.util.math import FixedSeed

from ..lowpoly import flat_shade
from ..materials import apply_palette


class _NoOpSurface:
    """Stand-in for upstream's bark surface that does nothing on apply.

    GenericTreeFactory.create_asset and finalize_placeholders both call
    `self.trunk_surface.apply(...)` to bake a photoreal bark shader into
    the trunk mesh. That shader build (and the underlying realize-pass
    on shader displacement) accounts for ~95% of upstream spawn cost
    on Maquette pine geometry — and we throw the result away when
    apply_palette assigns a flat color. Skipping it entirely takes
    spawns from ~10 s to fractions of a second.
    """

    @classmethod
    def apply(cls, *args, **kwargs):
        return None


class LowPolyTreeFactory(GenericTreeFactory):
    """A bare-trunk, low-poly tree factory.

    Mirrors `TreeFactory`'s species/season selection (so the upstream
    decision tree determines the genome) but skips the leaf/fruit
    collection construction entirely. The result is a faceted trunk +
    branches mesh.

    Constructor args:
        factory_seed     — same as upstream
        season           — "summer"/"winter"/"autumn"/"spring" or None
                            (auto-pick from seed)
        species          — genome archetype: "pine" (tall straight),
                            "random" (full upstream variety). Default
                            "pine" — Firewatch-style silhouette is
                            tall and slender; broadleaf genomes
                            produce gnarled fragments at low poly.
        target_face_size — face size used during create_asset's
                            adapt_mesh_resolution. Default 0.15 m
                            (vs upstream's typical 0.01–0.05). Trunk
                            radii are usually 0.05–0.5 m so 0.15
                            preserves trunk + main branch shape.
        palette_color    — Maquette palette key (e.g. "foliage_pine",
                            "rock_shadow") to apply as a single
                            material. None preserves upstream bark.

    All other kwargs forward to GenericTreeFactory.
    """

    def __init__(
        self,
        factory_seed,
        season: str | None = None,
        species: str = "pine",
        target_face_size: float = 0.15,
        target_polys: int = 1200,
        palette_color: str | None = None,
        **kwargs,
    ):
        with FixedSeed(factory_seed):
            if season is None:
                season = np.random.choice(["summer", "winter", "autumn", "spring"])

        with FixedSeed(factory_seed):
            if species == "pine":
                tree_params, _twig_params, _leaf_params = treeconfigs.pine_tree()
            elif species == "random":
                (tree_params, _twig_params, _leaf_params), _ = random_species(season)
            else:
                raise ValueError(f"unknown species {species!r}; expected 'pine' or 'random'")

        # Pass a no-op surface — we never want upstream's bark shader
        # because apply_palette overrides materials anyway, and the bark
        # shader's realize-pass is the bulk of spawn cost.
        super().__init__(
            factory_seed,
            tree_params,
            child_col=None,
            trunk_surface=_NoOpSurface,
            **kwargs,
        )
        self._maquette_target_face_size = float(target_face_size)
        self._maquette_target_polys = int(target_polys)
        self._maquette_palette_color = palette_color

    def create_asset(self, placeholder, face_size, distance, **kwargs) -> bpy.types.Object:
        # Bypass GenericTreeFactory.create_asset entirely: it does
        # SUBSURF (~4s) + REMESH SHARP (~7s) on a 230k-poly intermediate
        # just to collapse it back to ~1k polys. Both operations are
        # expensive and produce smoothing artifacts we don't want at
        # low poly. Take the raw skinned mesh, decimate to target
        # poly count, flat-shade, palette.

        skeleton_obj = placeholder.children[0]

        # Skin the skeleton — this is the only step from upstream we
        # actually need. ~0.2 s on pine geometry.
        skin_obj = self._create_coarse_mesh(skeleton_obj)

        # No-op trunk_surface.apply (kept for parity with upstream
        # parenting flow, and in case a subclass replaces _NoOpSurface).
        self.trunk_surface.apply(self, skin_obj)
        butil.parent_to(skeleton_obj, skin_obj, no_inverse=True)

        # Decimate the raw skinned mesh to the requested poly count.
        # COLLAPSE preserves silhouette better than UNSUBDIV at this
        # ratio range; ~0.2 s on a 230k-poly input.
        current_polys = max(len(skin_obj.data.polygons), 1)
        if current_polys > self._maquette_target_polys:
            ratio = self._maquette_target_polys / current_polys
            butil.modify_mesh(
                skin_obj,
                "DECIMATE",
                decimate_type="COLLAPSE",
                ratio=ratio,
                apply=True,
            )

        butil.parent_to(skin_obj, placeholder, no_inverse=True, no_transform=True)
        butil.parent_to(skeleton_obj, skin_obj, no_inverse=True)
        tag_object(skin_obj, "tree")
        butil.apply_modifiers(skin_obj)

        flat_shade(skin_obj)
        if self._maquette_palette_color is not None:
            apply_palette(skin_obj, self._maquette_palette_color)
        return skin_obj
