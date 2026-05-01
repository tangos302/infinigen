"""LoadedGltfFactory — drop-in factory for shipped CC0 GLB models.

Procedural factories are slow to write and converge on a small set of
shapes; the project's biggest variety win is loading existing CC0 game
assets and exposing them through the same factory interface the build
scripts already use.

This module:
  - Auto-discovers every ``*.glb`` inside ``runtime/models/<category>/``
    on first import. Each file becomes one archetype name (the file
    stem, lowercased).
  - Exposes one factory class per category — ``LoadedMedievalFactory``,
    ``LoadedNatureFactory`` — that accepts ``archetype="…"`` and works
    just like the procedural factories: instantiate, call ``spawn_asset``,
    place at a world coord.
  - Caches each GLB's mesh template after first load. Subsequent
    spawns are zero-cost ``object.copy()`` calls that share mesh data,
    so spawning 50 trees from the same archetype doesn't bloat the
    .blend.

Usage from a build script::

    from infinigen.maquette.runtime.loaded_factory import (
        LoadedMedievalFactory, LoadedNatureFactory
    )

    # List available archetypes (file stems):
    LoadedMedievalFactory.archetypes()  # ["wall-fortified-window",
                                        #  "tower-paint-base", …]

    # Spawn one:
    f = LoadedMedievalFactory(archetype="tower-paint-base", factory_seed=1)
    f.spawn_asset(i=0, loc=(2.0, -3.0, terrain.height_at(2.0, -3.0)))

The packs ship at low-poly count (Kenney game-ready, mostly a few
hundred verts each) so they don't need the post-spawn polycap that
realistic-mode factories use.
"""
from __future__ import annotations

import logging
import random
from pathlib import Path

logger = logging.getLogger(__name__)

_MODELS_DIR = Path(__file__).resolve().parent / "models"


def _scan_category(category: str) -> dict[str, Path]:
    """Walk ``models/<category>/`` for ``.glb`` files; return
    ``{archetype_name: filepath}``. Cached on the class via lazy load.
    """
    out: dict[str, Path] = {}
    cdir = _MODELS_DIR / category
    if not cdir.is_dir():
        return out
    for p in sorted(cdir.glob("*.glb")):
        out[p.stem.lower()] = p
    return out


class LoadedGltfFactory:
    """Base factory for GLB-loaded assets.

    Subclasses set ``_CATEGORY`` to pick a directory under
    ``runtime/models/``. Don't use this base directly — instantiate
    ``LoadedMedievalFactory`` / ``LoadedNatureFactory`` etc.
    """

    _CATEGORY: str = ""        # overridden in subclasses
    _ARCHETYPES: dict[str, Path] | None = None
    # Class-level cache: filepath → template object name. Cached lookups
    # let us share the same imported mesh across N spawn_asset() calls.
    _TEMPLATE_CACHE: dict[str, str] = {}

    def __init__(
        self,
        archetype: str | None = None,
        factory_seed: int = 0,
        *,
        scale: float = 1.0,
    ) -> None:
        self._ensure_registry()
        if archetype is None:
            # Roll a random archetype seeded by factory_seed so callers
            # get variety without specifying. Useful for scatter or
            # debug runs.
            rng = random.Random(int(factory_seed) ^ 0x9E37)
            archetype = rng.choice(sorted(self._ARCHETYPES.keys()))
        archetype = archetype.lower()
        if archetype not in self._ARCHETYPES:
            raise ValueError(
                f"{type(self).__name__}: archetype {archetype!r} not "
                f"found. Available (first 10): "
                f"{sorted(self._ARCHETYPES.keys())[:10]}"
            )
        self.archetype = archetype
        self.factory_seed = int(factory_seed)
        self.scale = float(scale)

    @classmethod
    def _ensure_registry(cls) -> None:
        if cls._ARCHETYPES is None:
            cls._ARCHETYPES = _scan_category(cls._CATEGORY)
            if not cls._ARCHETYPES:
                logger.warning(
                    "[LoadedGltfFactory] category %r has no .glb files in %s",
                    cls._CATEGORY, _MODELS_DIR / cls._CATEGORY,
                )

    @classmethod
    def archetypes(cls) -> list[str]:
        """Sorted list of available archetype names for this category."""
        cls._ensure_registry()
        return sorted(cls._ARCHETYPES.keys())

    @classmethod
    def _load_template(cls, path: Path):
        """Import the GLB once, cache the joined-mesh template by path.

        Returns the bpy template object. The template is hidden in
        viewport + render so it doesn't show up in the scene; spawns
        are copies that share its mesh data.
        """
        import bpy

        key = str(path)
        cached_name = cls._TEMPLATE_CACHE.get(key)
        if cached_name and cached_name in bpy.data.objects:
            return bpy.data.objects[cached_name]

        before = set(bpy.data.objects.keys())
        try:
            bpy.ops.import_scene.gltf(filepath=str(path))
        except RuntimeError as exc:
            logger.warning("GLB import failed %s: %s", path, exc)
            return None
        new_names = list(set(bpy.data.objects.keys()) - before)
        new_objs = [bpy.data.objects[n] for n in new_names]
        meshes = [o for o in new_objs if o.type == "MESH"]
        empties = [o for o in new_objs if o.type == "EMPTY"]

        # Kenney GLBs typically have ONE root + ONE mesh child. Prefer
        # the mesh; clean up the import-side empties.
        if not meshes:
            for o in new_objs:
                bpy.data.objects.remove(o, do_unlink=True)
            return None

        if len(meshes) > 1:
            # Some packs split a model into multiple meshes per material;
            # join them so a single object represents the asset.
            bpy.ops.object.select_all(action="DESELECT")
            for m in meshes:
                m.select_set(True)
            bpy.context.view_layer.objects.active = meshes[0]
            try:
                bpy.ops.object.join()
                template = meshes[0]
            except RuntimeError:
                template = meshes[0]
        else:
            template = meshes[0]

        # Strip parent transforms so the template sits at world origin
        # cleanly — spawn locations are then absolute.
        template.parent = None
        template.matrix_parent_inverse.identity()

        # Hide the template from render + viewport. Spawns will unhide.
        template.hide_render = True
        template.hide_viewport = True

        # Clean up empties / extra import objects we don't need.
        for o in empties:
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass

        cls._TEMPLATE_CACHE[key] = template.name
        return template

    def spawn_asset(self, i: int = 0, loc: tuple[float, float, float] = (0, 0, 0)):
        """Place a copy of the loaded asset at ``loc``. ``i`` is unused
        but accepted for parity with the upstream Infinigen
        ``AssetFactory.spawn_asset`` signature.
        """
        import bpy

        path = self._ARCHETYPES[self.archetype]
        template = self._load_template(path)
        if template is None:
            raise RuntimeError(
                f"could not load template for {self.archetype} ({path})"
            )

        spawn = template.copy()
        spawn.data = template.data  # share mesh data — cheap copies
        spawn.hide_render = False
        spawn.hide_viewport = False
        spawn.location = tuple(loc)
        spawn.scale = (self.scale, self.scale, self.scale)
        # Per-spawn micro rotation jitter so a stand of trees doesn't
        # show identical orientation. factory_seed + i feeds the rng.
        rng = random.Random(self.factory_seed * 7919 + int(i))
        spawn.rotation_euler.z = rng.uniform(0, 6.2831853)
        bpy.context.collection.objects.link(spawn)
        return spawn

    # Match upstream's ``factory()`` convention so callers can do
    # ``Factory(archetype="…")(i=0, loc=…)`` if they want.
    __call__ = spawn_asset


class LoadedMedievalFactory(LoadedGltfFactory):
    """Kenney CC0 medieval pack — buildings, walls, towers, docks,
    columns, barrels, fences. ~105 archetypes."""
    _CATEGORY = "medieval"
    _ARCHETYPES = None
    _TEMPLATE_CACHE: dict[str, str] = {}


class LoadedNatureFactory(LoadedGltfFactory):
    """Kenney CC0 nature pack — trees, rocks, plants, mushrooms,
    flowers, cliffs. ~329 archetypes."""
    _CATEGORY = "nature"
    _ARCHETYPES = None
    _TEMPLATE_CACHE: dict[str, str] = {}


# Convenience: filtered subsets of LoadedNatureFactory by name prefix
# so build scripts can roll a tree without browsing all 329 archetypes.
class LoadedTreeFactory(LoadedNatureFactory):
    """Subset of LoadedNatureFactory limited to ``tree_*`` archetypes."""
    _ARCHETYPES = None

    @classmethod
    def _ensure_registry(cls) -> None:
        if cls._ARCHETYPES is None:
            full = _scan_category(cls._CATEGORY)
            cls._ARCHETYPES = {k: v for k, v in full.items() if k.startswith("tree_")}


class LoadedRockFactory(LoadedNatureFactory):
    """Subset limited to ``rock_*`` archetypes."""
    _ARCHETYPES = None

    @classmethod
    def _ensure_registry(cls) -> None:
        if cls._ARCHETYPES is None:
            full = _scan_category(cls._CATEGORY)
            cls._ARCHETYPES = {k: v for k, v in full.items() if k.startswith("rock_")}


class LoadedPlantFactory(LoadedNatureFactory):
    """Subset limited to ``plant_*`` / ``flower_*`` / ``mushroom_*``."""
    _ARCHETYPES = None

    @classmethod
    def _ensure_registry(cls) -> None:
        if cls._ARCHETYPES is None:
            full = _scan_category(cls._CATEGORY)
            cls._ARCHETYPES = {
                k: v for k, v in full.items()
                if k.startswith(("plant_", "flower_", "mushroom_", "grass_", "lily_"))
            }
