"""Drive `claude -p` to generate a Blender build script for a prompt.

The runner is the single Claude invocation. It composes a context bundle
(FACTORIES_GUIDE.md + one canonical example) + the user prompt + system
instructions, then invokes `claude -p "<bundle>"` and parses the response
to extract the Python script.

Why `claude -p` instead of the API directly: keeps a single dependency
(`claude` CLI is already on the user's machine), inherits the user's
auth, and lets us swap in any Claude Code-compatible backend without
rewiring the pipeline.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .factories_guide import FORK_ROOT, MAQUETTE_DIR, write_guide

EXAMPLE_PATH = MAQUETTE_DIR / "pipeline" / "examples" / "medieval_village.py"


@dataclass
class GenerationResult:
    raw_response: str          # everything Claude returned
    extracted_script: str      # the Python script we'll run
    requested_assets: list[str]  # `# REQUESTED_ASSET: ...` lines
    debug_narrative: str | None = None  # extracted ## DEBUG_NARRATIVE block
    scene_title: str | None = None  # short human-readable title
    scene_plan: dict | None = None  # extracted ## SCENE_PLAN JSON


_SYSTEM_PROMPT = """\
You are the scene-build subprocess of the Maquette pipeline. You receive
a customer prompt for a 3D scene and a catalog of available factories.
You output a SINGLE Python script that, when run via `blender --background
--python script.py`, produces a stylized low-poly scene matching the
prompt and writes the render to `$MAQUETTE_OUT_DIR/scene.png` and a
.blend to `$MAQUETTE_OUT_DIR/scene.blend`.

CRITICAL RULES:

1. Output ONLY the Python script. No commentary before or after.
   Wrap the entire script in a ```python ... ``` fenced code block.
   Do not include any thinking or planning text outside the block.

2. Follow the canonical skeleton in the factory catalog (sys.path setup,
   ground plane, factory spawns, camera, sun, world bg, render to
   $MAQUETTE_OUT_DIR/scene.{png,blend}).

3. Only use factories that exist in the catalog below. If you wish a
   factory existed, write a `# REQUESTED_ASSET: <Name> — <purpose>`
   comment at the top of the script and BUILD THE SCENE ANYWAY using
   the closest existing factory as a stand-in. Do not refuse to build.

4. Use varied archetypes, scales, and rotations to avoid a uniform
   "instanced" look. Pick a lighting recipe that matches the prompt's
   mood (dawn, midday, golden hour, twilight, wasteland).

5. Object count caps:
     - Single-biome / canonical (size=80) scene: ~150 objects.
     - PANORAMA scene (size >= 120, eroded terrain): up to ~400 objects.
       Density matters here — a 280 BU wide panorama with only 25 trees
       reads as empty. Push 100+ trees, 20-30 buildings, 60+ boulders,
       and scatter them across the whole map (not just a ring).

6. DO NOT add `ShaderNodeVolumeScatter`, `ShaderNodeVolumeAbsorption`,
   any world-volume effects, or fog/mist/haze volumetrics. They render
   pure black at the low sample counts (32-48) we use. If the prompt
   mentions "fog", "mist", "haze", "dust", express it through the world
   background colour and sun warmth/dimness instead — never via a Volume
   shader.

7. Use the standard `archetype` parameter names from the catalog —
   `building_archetype`, `foliage_archetype`, `trunk_archetype`,
   `fence_archetype`, etc. There is no plain `archetype` kwarg on any
   factory; passing it will cause a runtime error.

8. The ground plane material should set `Base Color` directly. Do not
   add image textures, noise nodes, or shader graphs to materials —
   the Maquette aesthetic is solid flat colour per slot.

   FOLIAGE PALETTE: default tree foliage colour to `foliage_pine` or
   `foliage_bush`. The vivid keys (`foliage_mint`, `foliage_amber`,
   `foliage_rose`, `foliage_amethyst`, `foliage_lemon`, `foliage_coral`)
   are RESERVED for explicitly fantasy / enchanted / magical biomes —
   using mint trees in a normal forest reads as broken texture in the
   web viewer.

   FOLIAGE ARCHETYPES: default rotation is `pine_cone / round_ball /
   umbrella / bush`. The `crystal` archetype is faceted and reads as
   broken geometry against natural trees — use it ONLY for crystal
   forests or explicitly magical scenery.

   BOULDERS: `LowPolyBoulderFactory` defaults to a Maquette rock
   palette (rock_warm). You can override with `palette_color="rock_cool"`
   / `"rock_pale"` / `"rock_shadow"` per scene mood, but NEVER pass
   `palette_color=None` — the raw Infinigen Mountain shader doesn't
   round-trip through OBJ export and shows up as a pale grey blob
   in the viewer.

9. LIVE PROGRESS — call `checkpoint('<phase>')` at each major build
   boundary so the frontend's 3D viewer can show the scene evolving
   while the script runs. Required calls (skip any that don't apply):
     - after ground/terrain is in place:        checkpoint('terrain')
     - after primary foliage (trees, bushes):    checkpoint('foliage')
     - after buildings / structures:             checkpoint('structures')
     - after small props / scatter / fences:     checkpoint('props')
     - just before render:                       checkpoint('final')
   Import once near the top of the script:
     from infinigen.maquette.runtime.checkpoint import checkpoint
   Each call exports the current scene to map.obj — keep them at
   coherent visual milestones (don't checkpoint inside a tight loop).

10. SCENE TITLE — at the very top of your response (before any other
    section), output exactly one line:
      `## SCENE_TITLE: <short title>`
    The title must be 2-6 words, capitalised like a postcard ("Alpine
    Watchtower at Dusk", "Marketplace Under Banners"). It names the run
    in the history sidebar. NO trailing punctuation. NO scare quotes.

11. GROUND IS NEVER A BARE PLANE. Use the runtime terrain helper to
    build the ground mesh from a noise field; you also get a height
    sampler so placed objects rest on the surface instead of floating
    or clipping through. Required even for "flat" scenes (style="flat"
    explicitly returns z=0 everywhere — choose it deliberately).

      from infinigen.maquette.runtime.terrain import make_terrain

      terrain = make_terrain(
          style="rolling",       # see options below
          size=80,                # half-width in BU; world is -80..+80 BU
          base_color=(0.42, 0.50, 0.30, 1.0),
          seed=<scene seed>,      # match the rng seed for reproducibility
      )

    Default world size is 80 (i.e. 160 BU on a side). Scale assets and
    object counts to fill the bigger volume — a forest ring should sit
    at radius 30-50 BU, scatter clusters reach further, building groups
    spread out instead of huddling at the origin. Camera position scales
    too: position (40, -44, 26) targeting (0, 0, 3) frames a size=80
    world cleanly with lens 35.
      # Place objects on the surface:
      obj.location = (x, y, terrain.height_at(x, y))

    Style presets — pick by mood, not by guess:
      flat      courtyards, plazas, market squares, ship decks
      rolling   pastoral / valley / "rolling green hills"
      hilly     foothills, woodland clearings, broken country
      alpine    mountains, dramatic peaks, fantasy panoramas
      dunes     sandy waves, desert ripples

    For "alpine" scenes, do NOT also use LowPolyRockSpireFactory in
    the centre — the terrain already gives elevation. Use spires only
    as accent foreground/midground silhouettes. For water-bound scenes
    pick "rolling" or "flat" so the water surface doesn't poke through
    a peak.

    The water surface factory expects z≈0 — place lakes/rivers in a
    *valley* by sampling height_at at the lake centre and offsetting:

      cx, cy = 4, 8
      lake_z = terrain.height_at(cx, cy) - 0.4
      lake = LowPolyWaterSurfaceFactory(...).create_asset(placeholder=None)
      lake.location = (cx, cy, lake_z)

    Always call `checkpoint('terrain')` AFTER the make_terrain call.

11b. MULTI-BIOME TERRAIN. When the prompt mixes ground types — e.g.
    "grassland headland giving way to sandy beach and an ocean
    archipelago", "valley between snowy peaks and a desert plateau",
    "forested foothills bordering a marsh" — use
    `make_multi_biome_terrain` instead of `make_terrain`. Heights
    blend smoothly between zones; colors snap per-face by dominant
    zone (matches the faceted low-poly style):

      from infinigen.maquette.runtime.terrain import make_multi_biome_terrain

      terrain = make_multi_biome_terrain(
          size=80,
          seed=<scene seed>,
          zones=[
              # (style, center_x, center_y, radius)
              ("rolling", -30,   0, 25),   # grass headland
              ("dunes",    20,  -8, 22),   # sandy fringe
              ("flat",      0,  38, 30),   # ocean — water plane on top
              # optional 5th tuple element: (r, g, b) explicit color
          ],
      )

    Each zone uses the same style presets as `make_terrain`. Default
    colors per style: rolling=grass green, hilly=meadow green,
    alpine=rocky grey, dunes=sandy beige, flat=neutral mossy. Pick 2-4
    zones — too many produces a confused blend. For ocean-dominant
    scenes use style="flat" for the water region (the water surface
    factory adds the visible water plane on top).

    `terrain.height_at(x, y)` works the same as for single-biome:
    placement queries return the blended surface height. Same
    `checkpoint('terrain')` rule.

11c. EROIDED (GAME-READY) TERRAIN. When the prompt or attached image
    shows DRAMATIC topography — mountain ranges, river valleys
    threading through plains, "vast lands with a peak in the
    distance", "fjord coastline", "fantasy overland panorama" — use
    `make_eroded_terrain` instead of `make_terrain` /
    `make_multi_biome_terrain`. It runs hydraulic erosion via
    landlab's FastscapeEroder so ridges and river networks read as
    real topography (not noise on a plane), and writes per-vertex
    biome colors that blend continuously between meadow / forest /
    stone / alpine / snow:

      from infinigen.maquette.runtime.eroded_terrain import make_eroded_terrain

      terrain = make_eroded_terrain(
          size=140,
          seed=<scene seed>,
          peaks=[
              # (cx, cy, sigma, height_BU). height >= 12 BU gets
              # ridged-noise alpine character + snow capping.
              (115,  50, 25, 18.0),    # hero alpine NE
              (-110, 70, 18,  4.5),    # smaller western range
              (-95, -110, 22, 5.0),    # foreground vantage hill
          ],
          troughs=[
              # (cx, cy, sigma, depth_BU NEGATIVE). Chain 4-7 of these
              # to thread a winding river/lake basin; erosion carves
              # drainage from peaks toward troughs naturally.
              (-40, -10, 14, -3.6),
              ( 5,    5, 12, -3.4),
              ( 30,  20, 14, -3.2),
          ],
          plain_offset=2.4,    # lift plains so meadow dominates
          sea_level=0.5,       # below this = lakebed/shore color
          erode_iters=35,
      )

    Tuning rules:
      * Image references showing alpine peaks → 1 hero peak height
        14-22 BU, sigma 22-30, in the framed quadrant (e.g. NE).
      * Image with rolling plains + a single peak → keep plains
        smooth (no extra peaks), single peak height 14-18.
      * For a winding river: chain 5-7 troughs sigma 10-15 along
        the desired course, depth -3..-4. Don't overlap with peaks.
      * For "river through valley between mountains": peaks
        flanking the trough chain on both sides.
      * Bump `plain_offset` (e.g. 3.0) if the rendered scene reads
        as too sandy (too much shore band). Reduce (e.g. 1.5) if
        too much green and not enough exposed riverbed.

    Costs: ~5-10 seconds at the default resolution=256 (heightmap
    composition + erosion). Mesh + colors are sub-second.

    AUTO WATER: by default `make_eroded_terrain` detects connected
    basins (cells where elevation < sea_level) and drops one
    translucent blue cube per basin sized to its bbox — gives the
    impression of water bodies without any explicit factory call.
    DO NOT add `LowPolyWaterSurfaceFactory` on top of this helper;
    it duplicates the water and the explicit factory's flat slab
    looks wrong layered over the auto cubes. To suppress auto water
    (terrain-only renders), pass `water=False`.

    Always call `checkpoint('terrain')` AFTER the make_eroded_terrain call.

12. FACTORY SCALE DISCIPLINE.

    a) Factory base sizes are calibrated for a `size=80` world (160 BU
       wide) where the camera sits ~30-50 BU from the action. For a
       PANORAMA scene (size >= 120) the camera sits 150+ BU from the
       far ridge, so objects need to be MUCH SMALLER to read as
       "natural" distant scenery instead of dollhouse-sized props
       crowding the foreground.

         # PANORAMA rule (when using make_eroded_terrain with size >= 120):
         WORLD_SCALE = (size / 80.0) * 0.25     # ~0.44 at size=140
         # Objects within 25 BU of the camera can use ×2 of WORLD_SCALE
         # (foreground hero scale). Everything else = WORLD_SCALE.

         tree.scale = (s * WORLD_SCALE,) * 3       # default: distant
         hero_tree.scale = (s * WORLD_SCALE * 2,) * 3   # camera-adjacent

         house.scale = (s * WORLD_SCALE,) * 3
         castle_keep.scale = (s * WORLD_SCALE * 1.5, ...)   # landmark exception

       For canonical / single-biome / size=80 scenes, keep
       `WORLD_SCALE = 1.0` (no multiplier).

       Density matters as much as scale. In a panorama, MINIMUMS:

         Trees       :  120-180 (forest patches across plains, never a ring)
         Boulders    :   60-90  (riprap along water + scattered)
         Buildings   :   25-35  (1-2 hamlets along the river PLUS the castle)
         Windmills   :    2-4   (where they exist as a factory)
         Fences      :   15-25  (property lines on the plains)

       That's ~250+ objects per panorama scene. Within budget at the
       low polycounts these factories produce. Use seeded RNG loops:

         for i in range(140):
             fx = rng.uniform(-110, 110)
             fy = rng.uniform(-110, 110)
             fz = terrain.height_at(fx, fy)
             if fz < SEA_LEVEL + 0.4:    # don't drop trees in water
                 continue
             # ... build + place tree

       Spread positions across the FULL world, biased away from the
       castle compound and the water surface. Hand-listing 30
       positions inevitably looks patterned; the loop with seeded RNG
       reads as natural scatter.

    b) `LowPolyRockSpireFactory` produces 30+ BU tall sandstone
       columns (hoodoo / citadel / mesa archetypes). These are
       LANDMARK-scale, not scatter. Use AT MOST 1-2 spires per
       scene as hero silhouettes, never as "scattered outcrops".
       For scattered rocky outcrops use `LowPolyBoulderFactory` at
       scale 0.4-0.8 — those read as natural boulders.

    c) `LowPolyTombstoneFactory` is GRAVEYARD furniture. Do NOT
       scale it up to fake "ancient ruins" — the geometry still
       reads as gravestones from any distance. For fantasy ruins,
       use `LowPolyHouseFactory("tower")` at 0.5-0.8 scale, rotated
       slightly off-axis (rot_z = math.radians(rng.uniform(-15, 15)))
       and clustered 2-3 deep.

13. SKY / WORLD BACKGROUND COLOUR — picking the right preset.

    The Background node's color is the WHOLE sky for distant pixels.
    A flat warm tan (like 0.86, 0.78, 0.62) reads as DESERT DUST,
    not golden hour. Use these calibrated values per mood:

       Daytime clear         (0.62, 0.74, 0.88, 1.0)
       Golden hour (warm)    (0.78, 0.74, 0.72, 1.0)   # subtle warm-grey blue, NOT peach
       Overcast              (0.74, 0.76, 0.78, 1.0)
       Twilight              (0.42, 0.46, 0.58, 1.0)
       Stormy                (0.46, 0.48, 0.52, 1.0)
       Wasteland / dust      (0.78, 0.70, 0.55, 1.0)   # ONLY for desert/post-apoc
       Fantasy ethereal      (0.74, 0.78, 0.82, 1.0)

    NEVER pick a tan/peach colour just because the prompt says
    "warm" or "golden". Warmth comes from the SUN colour
    (rgb 1.0, 0.86, 0.65) hitting blue-grey sky-lit ground —
    not from painting the sky orange.

14. COMPOSITION RECIPES — concrete blueprints for landmarks the
    factory catalog doesn't have a single archetype for. Follow
    these literally; they're calibrated against the existing
    factory base sizes.

    14a. CASTLE / KEEP / FORTRESS.
         No `LowPolyCastleFactory` exists yet. To get a silhouette
         that READS as a castle from camera distance, compose it
         from existing factories with this exact recipe:

           # In panorama scenes the castle is a LANDMARK, not the
           # main subject — keep the silhouette readable but in
           # natural-distant proportions. Use the LANDMARK_SCALE
           # below, which is ~1.5× WORLD_SCALE (so it stands above
           # the mass of trees/houses but doesn't dwarf the alpine
           # peak behind it).
           LANDMARK_SCALE = WORLD_SCALE * 1.5

           # KEEP — tall central tower
           keep = LowPolyHouseFactory(
               factory_seed=<S>, building_archetype="tower",
           ).create_asset(placeholder=None)
           keep.scale = (1.1 * LANDMARK_SCALE, 1.1 * LANDMARK_SCALE, 1.6 * LANDMARK_SCALE)
           place(keep, cx, cy)   # cx, cy = castle hill peak

           # 3-4 WATCHTOWERS around the keep, smaller, ringing it.
           # Spacing is in WORLD-space BU; scale separately.
           for i, (dx, dy) in enumerate([(4, 0), (-4, 0), (0, 4), (0, -4)]):
               t = LowPolyHouseFactory(
                   factory_seed=<S>+10+i, building_archetype="tower",
               ).create_asset(placeholder=None)
               t.scale = (0.6 * LANDMARK_SCALE,) * 3
               place(t, cx + dx, cy + dy)

           # CURTAIN WALLS — stone-wall fence segments linking watchtowers
           for i, (mx, my, length, rot) in enumerate([
               (cx + 2, cy + 2, 4, math.radians(45)),
               (cx - 2, cy + 2, 4, math.radians(-45)),
               (cx + 2, cy - 2, 4, math.radians(135)),
               (cx - 2, cy - 2, 4, math.radians(-135)),
           ]):
               wall = LowPolyFenceFactory(
                   factory_seed=<S>+30+i,
                   fence_archetype="stone_wall",
                   length=length,
               ).create_asset(placeholder=None)
               wall.scale = (LANDMARK_SCALE, LANDMARK_SCALE, 2.0 * LANDMARK_SCALE)
               place(wall, mx, my, rot_z=rot)

           # GATEHOUSE — a small cottage marking the entrance
           gate = LowPolyHouseFactory(
               factory_seed=<S>+50, building_archetype="cottage",
           ).create_asset(placeholder=None)
           gate.scale = (0.7 * LANDMARK_SCALE,) * 3
           place(gate, cx + 6, cy)

         All castle parts live within a ~10 BU radius. Place the
         CASTLE on a hilltop (use `terrain.height_at(cx, cy)` to
         pick the high ground) so the silhouette stands above the
         meadow. ALWAYS emit:
           # REQUESTED_ASSET: LowPolyCastleFactory — fortress with curtain walls
         at the top of the script, so the request is logged.

    14b. RUINS / ANCIENT MONUMENTS.
         Reuse the watchtower piece from 14a — single tall tower
         scaled 0.4-0.7, rotated 5-15° off vertical
         (rotation_euler.x or .y, not just z), no walls, no gatehouse.
         Cluster 2-3 of them within 6 BU and add 4-6 boulders
         around their base for a "broken stone" look.
"""


def _read_text(p: Path) -> str:
    return p.read_text() if p.exists() else ""


_DEBUG_NARRATIVE_INSTRUCTIONS = """\

## DEBUG MODE — narrate your plan before writing the script

This is a DEBUG run. BEFORE the python build script, output a section
titled exactly:

```
## DEBUG_NARRATIVE
```

Walk through your plan in the ORDER and STRUCTURE below. Use the
exact subheadings shown. Designers read this to validate your choices
before looking at the script — vague or hand-waved sections waste
their time. Be concrete: archetype names, counts, placements, palette
keys.

### 1. Prompt understanding

What scene the user wants in your own words (1-2 sentences). If
reference images are attached, describe what you see in them: palette
(2-3 hex codes), silhouettes, density, mood. End with one sentence
that captures the feeling you're building toward — that sentence
governs every decision below.

### 2. Terrain + water (DECIDE THESE FIRST)

The ground plane and any water bodies set the biome and rule out half
the catalog. A snow biome forbids palm/cactus; an ocean-dominated
scene won't have a torii or windmill in the centre. Lock these in
before picking landmarks or objects.

For EACH factory you'll use from the **terrain** and **water**
categories, list:

- **Factory class name** (e.g. `LowPolyTreeFactory`)
- **Archetypes** — every one you plan to spawn, with explicit count
  per archetype (multiple archetypes per factory is encouraged for
  variety). Format: `pine × 8, dead × 2`.
- **Why these archetypes** — one sentence tying them to the biome
  and the governing feeling sentence from §1.

Then, separately:
- **Ground plane**: base colour as RGB tuple or hex AND the palette
  key it corresponds to (e.g. `ground_grass`).
- **Water present?** Yes/no. If yes: factory, archetype, footprint
  extent in BU. If no, say "no water — landlocked scene".

### 3. Landmarks (the 1-3 hero structures)

The focal points the camera frames. Same drill:

- **Factory + archetype(s) + per-archetype count**.
- **Layout**: centre, off-axis, on a rise, beside the water, etc.
- **Why this combo reads as the prompt's hero** — one sentence.

If the prompt has no obvious hero (open landscape), say so and skip
this section.

### 4. Objects / scatter / props (fill in around the heroes)

Everything decorating the scene without being the subject. Group by
factory; multiple archetypes per factory expected.

- **Factory + archetypes + counts**.
- **Where they cluster** — yard scatter, riprap edge, path props,
  forest ring, etc. Reference the canonical layout patterns from the
  catalog when applicable.

### 5. Missing factories OR missing archetypes

If you need an asset class OR an archetype-variant the catalog
doesn't have, follow this protocol for each gap. Do not skip steps.

a. **Name it.** Either a proposed `LowPoly<X>Factory` (whole missing
   class) OR `<ExistingFactory>:<archetype_name>` (archetype gap
   inside a factory that already exists).
b. **Describe.** Form, materials, scale (BU), function in the scene.
   2-3 sentences max.
c. **Compare.** List 1-3 closest existing factory+archetype
   candidates. For each, say what matches and what's missing. Rank
   them on this priority order — earlier criterion outranks later:
     1. **silhouette** (shape from camera distance)
     2. **materials** (colour family + finish)
     3. **scale** (relative size in the scene)
     4. **palette** (specific slot/colour-key match)
d. **Decide.** Pick one stand-in. Note any parameter tweaks
   (e.g. `scale=0.6`, `palette_color="rock_warm"`, `rotation_z=π/2`)
   that bridge the gap. The build script must use this stand-in.
e. **Emit.** Add a `# REQUESTED_ASSET: <name> — <one-line desc>`
   line at the top of the python script (whole-class gaps only;
   archetype gaps go as `# REQUESTED_ARCHETYPE: <Factory>:<arch> — <desc>`).

If you have NO gaps, write "No missing factories or archetypes — the
catalog covered the prompt cleanly."

### 6. Lighting + camera

- **Lighting recipe**: pick one preset name from the catalog
  (daytime / golden hour / dawn / twilight / wasteland-midday) and
  justify in one sentence why it matches the prompt's mood.
- **Camera**: position `(x, y, z)`, target `(tx, ty, tz)`, lens (35
  for wide scene, 50 for tight prop). One sentence on why this frame
  captures the hero subject from §3.

### 7. Machine-readable plan

After §6, emit a section titled exactly `## SCENE_PLAN` followed by a
single fenced ```json``` code block containing your plan as structured
JSON. The debug UI parses this to render categorised factory cards
with hover popovers. Schema (all fields required unless noted; use
empty arrays / null for absent ones — never omit keys):

```json
{
  "biome_summary": "one sentence — same as the §1 governing sentence",
  "ground": { "color_hex": "#aabbcc", "palette_key": "ground_grass | ground_sand | water | …" },
  "water_present": true,
  "terrain": [
    { "factory": "LowPolyTreeFactory",
      "archetypes": [ {"name": "pine", "count": 8}, {"name": "dead", "count": 2} ],
      "reasoning": "one sentence" }
  ],
  "water": [],
  "landmarks": [
    { "factory": "LowPolyHouseFactory",
      "archetypes": [ {"name": "cottage", "count": 1} ],
      "layout": "centre on rise",
      "reasoning": "one sentence" }
  ],
  "objects": [
    { "factory": "LowPolyBarrelFactory",
      "archetypes": [ {"name": "default", "count": 4} ],
      "cluster": "yard scatter",
      "reasoning": "one sentence" }
  ],
  "missing": [
    { "kind": "factory" or "archetype",
      "name": "LowPolyShrineFactory" or "LowPolyHouseFactory:tower",
      "description": "1-2 sentences",
      "stand_in": { "factory": "LowPolyHouseFactory", "archetype": "cottage", "tweaks": "scale=0.6" },
      "reasoning": "one sentence on why this beats other candidates" }
  ],
  "lighting": "twilight",
  "camera": { "position": [20, -22, 13], "target": [0, 0, 1.5], "lens": 35 }
}
```

The JSON must parse cleanly — no trailing commas, no comments inside,
no python-style booleans. Counts are integers. If a section has no
entries (e.g. a landlocked scene has no water), use `[]`. The factory
class names MUST exactly match those in the catalog above (exact
case + LowPoly prefix); archetype `name` strings must come from the
factory's archetype tuple.

---

After §7 ends, write the python build script in the usual
```python ... ``` fenced block. The script is the source of truth
for execution — your narrative + plan are for humans only and the
script must stand on its own.
"""


_CATEGORY_LABELS = {
    "terrain": "Terrain & Water (ground heightmap, water bodies, vegetation, rocks)",
    "landmarks": "Landmarks (hero structures: buildings, bridges, windmills, torii)",
    "objects": "Objects (props, scatter, fences, lanterns, banners, crates)",
}


def build_prompt(
    user_prompt: str,
    *,
    regenerate_guide: bool = True,
    reference_image_paths: list[Path] | None = None,
    debug: bool = False,
    include_categories: list[str] | None = None,
) -> str:
    """Assemble the full prompt: system instructions + factory catalog +
    canonical example + user prompt + optional reference image attachments.

    Reference images are injected as ``@<absolute_path>`` lines so Claude
    Code attaches them to the conversation; the model can then describe
    palette, silhouettes, and composition cues from the image while writing
    the build script."""
    if regenerate_guide:
        write_guide()
    guide = _read_text(MAQUETTE_DIR / "FACTORIES_GUIDE.md")
    example = _read_text(EXAMPLE_PATH)

    image_block = ""
    if reference_image_paths:
        ref_lines = "\n".join(
            f"@{Path(p).resolve()}" for p in reference_image_paths
        )
        image_block = (
            "## Reference image(s)\n\n"
            "Treat these as visual mood/composition references. Match their\n"
            "palette, silhouette, density, and overall vibe — but the prompt\n"
            "below is still the source of truth for content.\n\n"
            f"{ref_lines}\n\n"
        )

    debug_block = _DEBUG_NARRATIVE_INSTRUCTIONS if debug else ""

    # Restrict the build to a subset of factory categories. Used by the
    # debug "categories" toggle in the workbench when a designer wants
    # to iterate on just terrain or just landmarks. Always builds the
    # ground (otherwise the scene has no floor) but skips spawning
    # factories from any non-included category.
    category_block = ""
    valid_cats = {"terrain", "landmarks", "objects"}
    if include_categories is not None:
        included = [c for c in include_categories if c in valid_cats]
        excluded = [c for c in valid_cats if c not in included]
        if included and excluded:
            included_lines = "\n".join(f"  - {c}: {_CATEGORY_LABELS[c]}" for c in included)
            excluded_lines = "\n".join(f"  - {c}" for c in excluded)
            category_block = (
                "## CATEGORY RESTRICTION (debug mode)\n\n"
                "This is a partial-build run. Only spawn factories from the\n"
                "categories listed under INCLUDE. Skip every category under\n"
                "EXCLUDE — do not call any factory from those categories,\n"
                "and do not include them in the SCENE_PLAN's category arrays\n"
                "(use [] for excluded ones).\n\n"
                f"INCLUDE:\n{included_lines}\n\n"
                f"EXCLUDE:\n{excluded_lines}\n\n"
                "Always still build the ground via make_terrain — the scene\n"
                "needs a floor even if other categories are skipped.\n"
                "Camera + sun + world background are always required.\n\n"
            )

    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"## Factory catalog\n\n{guide}\n\n"
        f"## Canonical example — \"medieval village by a stream\"\n\n"
        f"This is the gold-standard build script you should pattern-match\n"
        f"on. Same structure (wipe → ground → spawns → camera → sun → world\n"
        f"→ render to $MAQUETTE_OUT_DIR), different content per prompt.\n\n"
        f"```python\n{example}\n```\n\n"
        f"{image_block}"
        f"{debug_block}"
        f"{category_block}"
        f"## YOUR TASK\n\n"
        f"User prompt: {user_prompt.strip() or '(blank — let the reference image(s) drive the build)'}\n\n"
        f"Generate the build script."
    )


_CODE_FENCE = re.compile(r"```python\s*\n(.*?)\n```", re.DOTALL)
_REQUESTED_LINE = re.compile(
    r"^\s*#\s*REQUESTED_ASSET:\s*(?P<rest>.+?)\s*$", re.MULTILINE
)


def extract_script(response: str) -> str:
    """Pull the Python script out of Claude's response. Handles fenced
    blocks; raises if none found."""
    match = _CODE_FENCE.search(response)
    if not match:
        # Fallback: if the response *is* a Python script (no markdown), use
        # it as-is. Heuristic: starts with "import" / "from" / a docstring.
        stripped = response.strip()
        first = stripped.splitlines()[0] if stripped else ""
        if first.startswith(("import ", "from ", '"""', "'''")):
            return stripped
        raise ValueError(
            "no ```python code block in Claude response and response doesn't "
            "look like a bare script. First 200 chars:\n" + stripped[:200]
        )
    return match.group(1)


def extract_requested_assets(script: str) -> list[str]:
    """Pull `# REQUESTED_ASSET: ...` markers from the script."""
    return [m.group("rest").strip() for m in _REQUESTED_LINE.finditer(script)]


_SCENE_TITLE_RE = re.compile(
    r"^##\s*SCENE_TITLE\s*:\s*(?P<title>.+?)\s*$",
    re.MULTILINE,
)


def extract_scene_title(response: str) -> str | None:
    """Pull the `## SCENE_TITLE: <...>` line from Claude's response.
    Returns None if no such line exists, the title (trimmed, no
    trailing punctuation, capped at 80 chars) otherwise."""
    match = _SCENE_TITLE_RE.search(response)
    if not match:
        return None
    raw = match.group("title").strip().strip('"\'')
    raw = raw.rstrip(".!?,;:")
    return raw[:80] or None


_SCENE_PLAN_RE = re.compile(
    r"^##\s*SCENE_PLAN\s*\n+```(?:json)?\s*\n(?P<body>.*?)\n```",
    re.MULTILINE | re.DOTALL,
)


def extract_scene_plan(response: str) -> dict | None:
    """Pull the `## SCENE_PLAN` JSON block from the response and parse
    it. Returns None on any failure — extraction is best-effort and
    must never block the build script execution path.

    Tolerant to:
      - missing ```json language tag
      - trailing whitespace / blank lines around the block
      - the rare model that puts the SCENE_PLAN inside the markdown
        narrative section instead of after it
    """
    import json as _json
    match = _SCENE_PLAN_RE.search(response)
    if not match:
        return None
    body = match.group("body").strip()
    if not body:
        return None
    try:
        data = _json.loads(body)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def extract_debug_narrative(response: str) -> str | None:
    """Extract the `## DEBUG_NARRATIVE` section from Claude's response.
    Returns None if no such section exists. The section ends at the next
    top-level heading or the start of the python fenced block."""
    match = re.search(
        r"^##\s*DEBUG_NARRATIVE\s*\n(?P<body>.*?)(?=^##\s|^```python|\Z)",
        response,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return None
    body = match.group("body").strip()
    return body or None


def call_claude(prompt: str, *, model: str | None = None,
                timeout_seconds: int = 300) -> str:
    """Run `claude -p <prompt>` and return stdout. The prompt is passed via
    stdin to avoid shell-arg-length limits."""
    if shutil.which("claude") is None:
        raise RuntimeError(
            "`claude` CLI not found on PATH. Install Claude Code or "
            "ensure the binary is in PATH for this user."
        )
    cmd = ["claude", "-p"]
    if model:
        cmd.extend(["--model", model])
    proc = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"`claude` exited {proc.returncode}.\n"
            f"stderr:\n{proc.stderr}\nstdout (first 2k):\n{proc.stdout[:2000]}"
        )
    return proc.stdout


def generate(user_prompt: str, *, model: str | None = None,
             timeout_seconds: int = 300,
             regenerate_guide: bool = True,
             reference_image_paths: list[Path] | None = None,
             debug: bool = False,
             include_categories: list[str] | None = None) -> GenerationResult:
    """End-to-end: prompt → Claude → extracted script."""
    full_prompt = build_prompt(
        user_prompt,
        regenerate_guide=regenerate_guide,
        reference_image_paths=reference_image_paths,
        debug=debug,
        include_categories=include_categories,
    )
    response = call_claude(full_prompt, model=model, timeout_seconds=timeout_seconds)
    script = extract_script(response)
    requested = extract_requested_assets(script)
    narrative = extract_debug_narrative(response) if debug else None
    plan = extract_scene_plan(response) if debug else None
    title = extract_scene_title(response)
    return GenerationResult(
        raw_response=response,
        extracted_script=script,
        requested_assets=requested,
        debug_narrative=narrative,
        scene_title=title,
        scene_plan=plan,
    )
