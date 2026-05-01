"""Polycount-cap mixin for realistic factories.

Upstream Infinigen factories produce research-quality meshes (1-2 M
verts per tree, 200k+ for ferns). For the songe pipeline we target
PS3-era polycounts: a few thousand triangles per hero asset, a few
hundred per ground-cover prop. Anything heavier obliterates browser
GPUs and inflates render memory.

Strategy: post-spawn DECIMATE COLLAPSE to a per-factory budget. Wraps
each `Realistic*Factory.spawn_asset()` so the cap is invisible to the
build script — call the factory normally and get a capped mesh back.

Per-factory targets are set in `factories_realistic/__init__.py` via
`with_polycap(cls, target_verts=...)`. Pass `target_verts=None` to
disable the cap for a specific class (the structural / abstract
factories already produce <1k verts and don't need it).
"""

from __future__ import annotations

import logging

import bmesh
import bpy

logger = logging.getLogger(__name__)


def _weld_close_verts(obj: bpy.types.Object, distance: float = 0.005) -> int:
    """Merge nearby vertices via bmesh (headless-safe).

    Returns the number of vertices removed. Doing this via bmesh
    instead of `bpy.ops.mesh.remove_doubles` avoids the EDIT-mode
    operator which silently fails under `blender --background` if
    the mesh wasn't entered through a 3D-View context.
    """
    if obj is None or obj.data is None or not hasattr(obj.data, "vertices"):
        return 0
    n_before = len(obj.data.vertices)
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=distance)
        bm.to_mesh(obj.data)
    finally:
        bm.free()
    obj.data.update()
    return n_before - len(obj.data.vertices)


def _decimate_to(obj: bpy.types.Object, target_verts: int) -> bpy.types.Object:
    """Bake modifiers + DECIMATE COLLAPSE down to target vertex count.

    Two-step:
      1. Convert to mesh (`bpy.ops.object.convert(target='MESH')`) which
         bakes all geometry-nodes / particle / armature modifiers into
         static mesh data. Without this the DECIMATE sees only the
         base mesh (often tiny) while the evaluated output stays huge —
         e.g. fern's geometry-nodes leaflets, grass-tuft instancer.
      2. DECIMATE COLLAPSE to ratio = target / current_verts.

    Idempotent: under-budget meshes skip both steps.
    """
    if obj is None or not hasattr(obj, "data") or obj.data is None:
        return obj
    if not hasattr(obj.data, "vertices"):
        return obj

    prev_active = bpy.context.view_layer.objects.active
    prev_selected = [o for o in bpy.context.selected_objects]

    def _activate_only(target_obj):
        bpy.ops.object.select_all(action="DESELECT")
        target_obj.select_set(True)
        bpy.context.view_layer.objects.active = target_obj

    def _restore_selection():
        bpy.ops.object.select_all(action="DESELECT")
        for o in prev_selected:
            try:
                o.select_set(True)
            except (ReferenceError, RuntimeError):
                pass
        bpy.context.view_layer.objects.active = prev_active

    try:
        # Step 1 — snapshot the evaluated (post-modifier, post-geo-nodes)
        # mesh and replace obj.data with it. This is the only reliable
        # way to capture geometry-nodes output for decimation; the
        # bpy.ops.object.convert(target='MESH') operator silently
        # leaves some upstream node graphs un-flattened (notably the
        # fern's leaflet instancer).
        if len(obj.modifiers) > 0:
            try:
                depsgraph = bpy.context.evaluated_depsgraph_get()
                obj_eval = obj.evaluated_get(depsgraph)
                baked = bpy.data.meshes.new_from_object(
                    obj_eval, preserve_all_data_layers=True, depsgraph=depsgraph,
                )
                old_data = obj.data
                obj.data = baked
                # Remove the now-orphaned base mesh to keep the .blend
                # tidy (several MB per fern otherwise).
                if old_data.users == 0:
                    bpy.data.meshes.remove(old_data)
                # Clear modifiers — they've been baked into the new mesh.
                obj.modifiers.clear()
            except RuntimeError as exc:
                logger.warning(
                    "PolyCap evaluated-snapshot failed on %s: %s — "
                    "decimating base mesh only",
                    obj.name, exc,
                )

        # Step 2 — DECIMATE COLLAPSE, iterated, with a plateau-breaking
        # weld pass when needed.
        #
        # Blender's COLLAPSE decimator has a per-island topology floor:
        # on meshes with thousands of disconnected components (fern's
        # per-leaflet islands, dense particle scatters), each island
        # decimates to a per-island floor and the asset stalls at
        # 10x-100x over budget. The fix when we plateau: weld nearby
        # vertices together so islands merge, then continue decimating.
        #
        # We don't weld unconditionally because clean meshes (tree,
        # boulder) collapse fine in 1-2 passes and welding their already-
        # tight topology damages silhouettes.
        mod_name = "MaquettePolyCap"
        # Progressive weld thresholds — kick in only when DECIMATE alone
        # can't reach target. Each entry is a (min_iter_idx, threshold).
        # Tree/boulder hit target by iter 1 and never reach the weld
        # branch; fern-style island-heavy meshes plateau and need the
        # weld series to break through.
        weld_schedule = [(2, 0.02), (4, 0.05), (6, 0.1)]
        welds_done = 0
        for iter_idx in range(10):
            n = len(obj.data.vertices)
            if n <= target_verts:
                break
            if (
                welds_done < len(weld_schedule)
                and iter_idx >= weld_schedule[welds_done][0]
                and n > 2 * target_verts
            ):
                threshold = weld_schedule[welds_done][1]
                removed = _weld_close_verts(obj, distance=threshold)
                logger.debug(
                    "PolyCap weld pass %d on %s @ %.3fm: removed %d verts",
                    welds_done + 1, obj.name, threshold, removed,
                )
                welds_done += 1
                continue
            ratio = max(0.05, min(1.0, target_verts / n))
            mod = obj.modifiers.new(mod_name, "DECIMATE")
            mod.decimate_type = "COLLAPSE"
            mod.ratio = ratio
            try:
                _activate_only(obj)
                bpy.ops.object.modifier_apply(modifier=mod_name)
            except RuntimeError as exc:
                logger.warning(
                    "PolyCap decimate failed on %s (%d->%d): %s",
                    obj.name, n, target_verts, exc,
                )
                if mod_name in obj.modifiers:
                    obj.modifiers.remove(obj.modifiers[mod_name])
                break
    finally:
        _restore_selection()

    return obj


_UPSTREAM_FACTORY_CHILD_PREFIXES: tuple[str, ...] = (
    # Re-enabled 2026-05-01 with a guard. Earlier the cleanup broke
    # subsequent spawns because the spawned tree's GN graph still
    # referenced the orphans. Polycap now bakes the asset to a static
    # mesh via `bpy.data.meshes.new_from_object(evaluated)`, severing
    # those references. So at the moment our wrapper returns, the
    # orphans truly are orphan: deleting them frees ~700k verts of
    # FruitFactory / LeafFactory / GenericTreeFactory / BranchFactory
    # template meshes, dropping a typical tree-included .blend from
    # ~660 MB to a few tens of MB.
    #
    # The cleanup still skips any orphan whose mesh data is shared
    # with the retained asset (defensive — we never WANT to delete
    # something the kept mesh still references).
    "FruitFactory",
    "LeafFactory",
    "BranchFactory",
    "GenericTreeFactory",
    "TwigFactory",
)


def _clean_upstream_orphans(retained: bpy.types.Object) -> int:
    """Delete factory-child template objects we don't want to ship.

    Walks `bpy.data.objects`, removing anything whose name matches the
    upstream helper prefixes — EXCEPT:
      - The retained asset itself.
      - Anything whose mesh data is shared with the retained asset (a
        belt-and-braces guard against deleting something the kept mesh
        still references; rare but possible if a future polycap path
        skips the evaluated-snapshot step).

    Also deletes orphan mesh blocks (`bpy.data.meshes` with users==0)
    after the object pass; a tree run leaves several MB of mesh-only
    orphans referenced by nothing once the wrapper objects are gone.

    Returns the number of objects removed (informational).
    """
    if retained is None:
        return 0
    retained_data = retained.data
    n = 0
    for obj in list(bpy.data.objects):
        if obj is retained:
            continue
        if not obj.name.startswith(_UPSTREAM_FACTORY_CHILD_PREFIXES):
            continue
        if obj.data is retained_data:
            continue  # would orphan the retained mesh
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
            n += 1
        except (RuntimeError, ReferenceError):
            pass

    # Garbage-collect mesh blocks that lost their last user. Without
    # this, removing the wrapper Objects above doesn't reclaim the
    # underlying mesh bytes — they just become orphan datablocks that
    # survive into the .blend save.
    for me in list(bpy.data.meshes):
        if me.users == 0:
            try:
                bpy.data.meshes.remove(me)
            except (RuntimeError, ReferenceError):
                pass

    return n


def with_polycap(cls: type, target_verts: int | None) -> type:
    """Return a subclass of ``cls`` that applies a polycount cap +
    upstream-orphan cleanup to every spawn_asset() return value.

    Pass ``target_verts=None`` to disable the polycount cap; orphan
    cleanup still runs since unused FruitFactory / LeafFactory templates
    are a separate file-size problem from per-asset polycount.
    """
    base_spawn = cls.spawn_asset

    def spawn_asset(self, *args, **kwargs):
        obj = base_spawn(self, *args, **kwargs)
        # spawn_asset can return (obj, export_path, semantic_mapping) when
        # `export=True` is passed; only cap the leading object.
        if isinstance(obj, tuple) and obj and hasattr(obj[0], "data"):
            primary = obj[0]
            if target_verts is not None:
                primary = _decimate_to(primary, target_verts)
            _clean_upstream_orphans(primary)
            obj = (primary, *obj[1:])
        else:
            if target_verts is not None:
                obj = _decimate_to(obj, target_verts)
            _clean_upstream_orphans(obj)
        return obj

    capped = type(
        cls.__name__,
        (cls,),
        {
            "spawn_asset": spawn_asset,
            "_polycap_target_verts": target_verts,
            "__module__": cls.__module__,
            "__qualname__": cls.__qualname__,
            "__doc__": cls.__doc__,
        },
    )
    # Preserve `__call__ = spawn_asset` convenience binding from
    # AssetFactory.
    capped.__call__ = spawn_asset
    return capped
