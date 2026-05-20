# Animation readiness — native factory conventions

There is a plan to animate generated scenes (foliage wind, mechanical motion, etc.).
Full plan: `songe/docs/animation-integration-plan.md`. This note is only the part that affects factory authoring.

## TL;DR

Mechanical animation (windmill blades, watermill wheel, banner cloth, bell, ...) is currently
**blocked**: every factory emits one monolithic mesh — moving parts are merged faces separated
only by `material_index`. Fixing that ("Tier 2") needs infra changes first (the
`AssetFactory.create_asset -> bpy.types.Object` single-object contract, `apply_palette_slots`,
placement). **Do not split objects yet** — it will break silently.

## Do now (near-zero cost, helps immediately)

1. **Semantic object names.** Name the factory's output object by type — `Windmill`, `OakTree`,
   `Banner` — not `Object.001`. The OBJ export keeps these as `o`-groups; the viewport uses them
   to classify what is foliage / water / etc.
2. **Semantic material names.** The moving-part material name should contain a keyword —
   `blade`, `foliage`, `leaf`, `cloth`, `flame`, `water`. Survives both OBJ (`usemtl`) and glTF.
3. **Document the moving-part `material_index`** for each factory that has one (you already use
   slot ranges — just record which slot moves).

## Defer to Tier 2 (needs the infra spike first)

- Author moving parts as **separate (parented) child objects**.
- Place each part's **local origin at its pivot** (blade hub, banner pole base, bell yoke).
  Helps glTF only — OBJ discards transforms.
- **Custom properties / metadata** (helps glTF only):
  - `songe:kind` — `"windmill_blades"`, `"foliage"`, `"banner_cloth"`, `"torch_flame"`, ...
  - `songe:motion` — `{"type":"rotate","axis":[0,0,1],"rpm":12}` / `{"type":"sway",...}` /
    `{"type":"hinge","axis":[0,1,0]}` / `{"type":"flicker"}`
  - per-vertex sway weight — a custom vertex attribute / 2nd color layer.
  - For these to reach the browser, `_scene_to_glb` in `runtime/lod_bake.py` must also pass
    `export_extras=True` (absent today).

## What helps which format

| Convention                       | OBJ                                   | glTF |
|-----------------------------------|---------------------------------------|------|
| Semantic object names             | yes                                   | yes  |
| Semantic material names           | yes                                   | yes  |
| Separate (parented) part objects  | yes                                   | yes  |
| Local origin at pivot             | no (transforms discarded)             | yes  |
| Custom properties / metadata      | no                                    | yes  |
| Per-vertex sway weight            | no (single color channel already used)| yes  |
