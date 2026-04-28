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

from infinigen.assets.composition import material_assignments
from infinigen.assets.objects.trees import treeconfigs
from infinigen.assets.objects.trees.generate import (
    GenericTreeFactory,
    random_species,
)
from infinigen.core.util.math import FixedSeed
from infinigen.core.util.random import weighted_sample

from ..lowpoly import flat_shade
from ..materials import apply_palette


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
            trunk_surface = weighted_sample(material_assignments.bark)

        super().__init__(
            factory_seed,
            tree_params,
            child_col=None,
            trunk_surface=trunk_surface,
            **kwargs,
        )
        self._maquette_target_face_size = float(target_face_size)
        self._maquette_palette_color = palette_color

    def create_asset(self, placeholder, face_size, distance, **kwargs) -> bpy.types.Object:
        skin_obj = super().create_asset(
            placeholder,
            self._maquette_target_face_size,
            distance,
            **kwargs,
        )
        flat_shade(skin_obj)
        if self._maquette_palette_color is not None:
            apply_palette(skin_obj, self._maquette_palette_color)
        return skin_obj
