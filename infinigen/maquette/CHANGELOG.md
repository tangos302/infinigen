# Maquette Pipeline Changelog

## alpha-0.12 — 2026-05-01 — Realistic mode

The pipeline now has two modes (`maquette_mode`):

- **`low_poly`** (default) — stylized maquette factories with flat
  shading + palette material. Existing behaviour, unchanged.
- **`realistic`** — upstream Infinigen + addon-derived factories with
  full procedural shaders and PBR materials. Polycap-managed for
  browser playback. New in this release.

### Realistic-mode catalog (33 factories, 130+ archetype variants)

**Vegetation (8)**: Tree (4 seasons), Bush, Fern, Flower, FlowerPlant,
Dandelion, GrassTuft, Mushroom.

**Arid (4)**: Cactus (4 morphologies), SnakePlant, SpiderPlant, Succulent.

**Rocks (3)**: Boulder (slab/boulder), BlenderRock (pebbles),
GlowingRocks (emissive). *BoulderPile is disabled in v1 — use Boulder ×N.*

**Underwater (4)**: Seaweed, KelpMonocot, Coral (7 morphologies via
dispatcher), Urchin.

**Structures (4)**: Wall (5 archetypes — boundary / fortress / ruin /
tower_round / garden_low), Beam (6 profiles — box / u / c / l / i / t),
StepPyramid (4 sizes), PipeJoint (3 elbow angles).

**Mechanical (3)**: Gear (4 archetypes), WormGear (3 archetypes),
Gemstone (4 cuts).

**Geometric / abstract (5)**: Solid (7 Platonic/Archimedean), Supertoroid
(4 archetypes), Honeycomb (4 archetypes), MengerSponge (3 fractal levels),
FunctionSurface (4 math archetypes).

**Architecture (1)**: BToolsBuilding (5 archetypes — cottage /
two_storey / barn / tower / longhouse). Wraps ranjian0/building_tools
v1.0.13. First non-Infinigen-derived realistic factory.

Total catalog growth this release: 0 → 33 realistic factories.
Low-poly catalog (29) untouched — both modes coexist.

### Infrastructure

- **Polycount caps** (`factories_realistic/_polycap.py`): post-spawn
  DECIMATE COLLAPSE + plateau-breaking weld pass to a per-factory
  vertex budget. Tree 1.4M → 4k, fern 2.1M → 1.5k. PS3-era target
  polycounts across the catalog.
- **Upstream orphan cleanup**: deletes FruitFactory / LeafFactory /
  GenericTreeFactory templates left over from upstream factory
  initialisation. Cuts .blend size 4× (~700k orphan verts per render
  removed).
- **Default PBR materials** (`factories_realistic/_materials.py`):
  applied at wrap time to structural / abstract factories that
  upstream leaves untextured (Wall, Beam, Pyramid, Pipe, Solid,
  Supertoroid, Honeycomb, Menger, FnSurface, Gear, Gemstone).
- **Scatter helper** (`runtime/realistic_scatter.py`): spawn 1
  template + scatter as instanced geometry. Sidesteps the upstream
  >5-tree spawn bug for forests / dense vegetation.
- **LOD bake stage** (`runtime/lod_bake.py`): triggered automatically
  for realistic-mode runs. Blender → GLB → gltf-transform pipeline
  (dedup → instance → simplify → quantize → draco). Writes
  `scatter.json` manifest for the frontend.
- **Hybrid landmark policy**: realistic-mode runs import the
  LowPoly* landmark factories (House, Windmill, Bridge, etc.)
  alongside the realistic vegetation / rocks for buildings that don't
  have a realistic equivalent. Mild aesthetic mismatch is acceptable
  v1 trade-off.

### Frontend

- **Workbench mode toggle** (`generate-workbench.tsx`): segmented
  Low-poly / Realistic button next to the Sonnet / Opus model picker.
  Persists to localStorage.
- **Three.js viewer** (`pipeline-map-viewer.tsx`): new `LoadedGlb`
  component prefers the LOD-baked GLB + `scatter.json` over the
  legacy OBJ when present. GLTFLoader + DRACOLoader wired up.
- **Type contract** (`map-contract.ts`): `MaquetteMode` type added,
  threaded through `GenerateRequest` → API route → backend.

### Upstream patches

The fork applies four small patches to upstream Infinigen for Blender
4.2 + numpy 2.x compatibility:

1. `core/nodes/node_utils.py::assign_curve` — handles Blender 4.2's
   `CurveMapPoints.new()` returning NULL on x-collisions, plus
   numpy 2.x's stricter implicit float conversion. Unblocks fern,
   mushroom, tree leaf shaders.
2. `assets/objects/rocks/pile.py` — three patches to BoulderPile
   (placeholder children expectation, missing `i` arg, positional-arg
   mix-up). Even with these, BoulderPile still has a downstream silent
   exit; the wrapper raises NotImplementedError directing callers to
   spawn multiple Boulders instead.

### Building Tools addon (third-party)

- Installed at `~/.config/blender/4.2/scripts/addons/building_tools/`
  (v1.0.13, GPL-3, ranjian0).
- Two patches applied for Blender 4.2 + Python 3.11 compatibility:
  - `btools/api/options.py` — mutable dataclass defaults rewritten
    to `field(default_factory=...)`.
  - `btools/utils/util_common.py::crash_safe` — popup_message skipped
    when no window manager is available (was crashing in headless).

### Known limitations

- `RealisticTreeFactory` silent-exits scripts at >5 spawns (upstream
  twig-collection accumulation). Workaround: scatter_template.
- `RealisticBoulderPileFactory` disabled (cascading upstream bugs).
- `RealisticMengerSpongeFactory` "snub_cube" archetype falls back to
  cube (parameter tuning needed).
