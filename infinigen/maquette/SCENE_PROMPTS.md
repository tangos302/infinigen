# Scene Prompts → Asset Gap Analysis

A customer-simulation exercise. We imagine prompts a Songe user would
type, mentally walk the scene, and identify which objects we have
factories for vs. which we don't. The missing-object specs at the
bottom are **parametric generation rules** — same shape as the
existing `LowPolyHouseFactory`, `LowPolyBoulderFactory`,
`NativeLowPolyTreeFactory` — so they can be implemented in atomic
commits later.

## Conventions in this doc

Each missing-object spec has:

- **Class name** — `LowPolyXxxFactory`, parallel to existing factories
- **Key dimensions** — the parametric handles a caller cares about
- **Archetypes** — discrete variants the factory should support
  (`fence_archetype="picket" | "post_and_rail" | …`)
- **Defaults** — sensible value per archetype
- **Material slots** — palette keys per region (walls / roof / accent /
  foundation pattern from existing factories)
- **Polycount target** — order of magnitude
- **Implementation hints** — bmesh primitives, complexity flag

This doc is the running spec list. Add prompts at the top, add specs
at the bottom, in priority order. **Update prio when something gets
implemented or rendered.**

Status legend:
- ✅ have a factory
- 🟡 partial (works for some prompts, gaps for others)
- ❌ missing

---

## Empirical attempt log

These prompts were ACTUALLY built via MCP using only existing
factories. The "GAPS HIT" tables below are confirmed by attempting
the build, not just imagined.

### Attempt 1 — "medieval village by a stream"

Built 2026-04-28 via MCP:
- ✅ 6 houses (cottage, longhouse, cottage, cabin, barn, tower)
  arranged on one bank
- ✅ 14 mixed-archetype trees
- ✅ 12 boulders
- Saved: `_artifacts/maquette/prompt_medieval_village.{png,blend}`

**Gaps hit (could not build with current factories):**

| Missing factory | Why the prompt needed it |
|---|---|
| `LowPolyWaterSurfaceFactory` | the stream is the focal feature |
| `LowPolyBridgeFactory` | "by a stream" implies pedestrian crossing |
| `LowPolyPathFactory` | dirt paths between buildings |
| `LowPolyFenceFactory` | enclosed yards / crop plots |
| `LowPolyWellFactory` | medieval village square staple |
| `LowPolyLanternPostFactory` | exterior lighting |
| `LowPolyBarrelFactory` | props by doors and stalls |
| `LowPolyCrateFactory` | (paired with barrel) |
| `LowPolySignpostFactory` | path junctions |

**Result**: scene reads as "houses in a forest", not "village by a stream".
The water + crossing + paths are doing the heavy narrative lifting in
the prompt and we have none of that.

### Attempt 2 — "abandoned forest campsite at dusk"

Built 2026-04-28 via MCP:
- ✅ 20 trees as a forest ring
- ✅ 8 boulders in the clearing
- Saved: `_artifacts/maquette/prompt_campsite.{png,blend}`

**Gaps hit:**

| Missing factory | Why |
|---|---|
| `LowPolyCampfireFactory` | stone ring + crossed logs — focal point of any campsite |
| `LowPolyTentFactory` | ridge-pole tent — core campsite asset |
| `LowPolyLogFactory` | fallen logs to sit on (NEW — not in initial spec list) |
| `LowPolyLanternPostFactory` | hanging lantern for atmosphere |
| `LowPolyBarrelFactory` | supplies |
| `LowPolyCrateFactory` | supplies |
| `LowPolyAxeStumpFactory` | stump-with-axe is the stylized "abandoned camp" tell (NEW) |

**Result**: scene reads as "empty forest clearing". The campsite is
implied by the prompt's narrative but invisible — every signature
prop is missing.

### Attempt 3 — "Wild West frontier town main street"

Built 2026-04-28 via MCP:
- ✅ 6 buildings (saloon=longhouse, bank/sheriff=cottages, store=longhouse,
  water tower=tower compromise, stables=barn)
- ✅ 6 sparse trees on outskirts, 8 boulders
- Saved: `_artifacts/maquette/prompt_western.{png,blend}`

**Gaps hit (10):** Boardwalk, HitchingPost, Wagon, Windmill,
Tumbleweed, Fence, Barrel, Crate, LanternPost, WaterTower.

NEW factories discovered: `LowPolyBoardwalkFactory`,
`LowPolyWagonFactory`, `LowPolyTumbleweedFactory`,
`LowPolyWaterTowerFactory`.

### Attempt 4 — "lakeside fishing village"

- ✅ 5 houses, 8 reed-archetype trees on the bank, 6 boulders
- Saved: `_artifacts/maquette/prompt_fishing_village.{png,blend}`

**Gaps hit (8):** WaterSurface, Pier, Boat, FishingNet, Buoy,
LanternPost, Barrel, Fence.

NEW factories discovered: `LowPolyFishingNetFactory`,
`LowPolyBuoyFactory`.

### Attempt 5 — "fantasy mountain monastery"

- ✅ Monastery (tower + 2 longhouse wings), 8 sparse pines, 12 boulders as scree
- Saved: `_artifacts/maquette/prompt_monastery.{png,blend}`

**Gaps hit (8):** Mountain, StonePath, Statue, PrayerFlag, Column,
Brazier, Arch, Bell.

NEW factories discovered: `LowPolyMountainFactory`,
`LowPolyStonePathFactory`, `LowPolyPrayerFlagFactory`,
`LowPolyColumnFactory`, `LowPolyBrazierFactory`, `LowPolyBellFactory`.

### Attempt 6 — "ancient ruins at edge of forest"

- ✅ 3 hacked "ruined" houses (flat roof + low walls + no chimney), 15
  trees forming forest edge, 15 boulders as scattered masonry
- Saved: `_artifacts/maquette/prompt_ruins.{png,blend}`

**Gaps hit (8):** Arch, Column, BrokenWall, Monolith, Vine,
Tombstone, Altar, Rubble.

NEW factories discovered: `LowPolyBrokenWallFactory`,
`LowPolyVineFactory`, `LowPolyTombstoneFactory`,
`LowPolyAltarFactory`, `LowPolyRubbleFactory`.

### Attempt 7 — re-run "medieval village" with Tier-1 factories built

Built 2026-04-28 via headless Blender, after shipping LanternPost,
Fence, Barrel, and Crate factories. Same prompt as Attempt 1 — verifies
the empirical loop closes.

- ✅ 5 houses (cottage / longhouse / cabin / tower) around a square
- ✅ 24 trees (5-archetype mix) framing the village
- ✅ 8 boulders on the periphery
- ✅ 4 fences across all archetypes (picket, post-and-rail, stone wall,
  wooden plank) defining yards / corral / boundaries
- ✅ 4 lanterns (2 iron post + 1 stone brazier + 1 wooden post) at the
  square + by houses
- ✅ 2 barrels (one upright, one on its side) by cottage door + longhouse
- ✅ 5 crates (mixed wooden/fragile/metal) in stacks by tower + longhouse
- Saved: `_artifacts/maquette/prompt_medieval_village_v2.{png,blend}`

**Result**: scene reads as "medieval village" — lanterns light the
square, fences enclose plots, crates stack as cargo. The Firewatch
silhouette holds across all the new props.

**Remaining gaps for this prompt** (still not buildable):
WaterSurface, Bridge, Path, Well, Signpost. Stream is still the
dominant missing element — confirms WaterSurface as next priority.

### Cross-attempt frequency (6 attempts)

| Factory | Attempts where it's missing |
|---|---|
| LowPolyFenceFactory | medieval, western, fishing, monastery (4) |
| LowPolyLanternPostFactory | medieval, campsite, western, fishing, monastery (5) |
| LowPolyBarrelFactory | medieval, campsite, western, fishing (4) |
| LowPolyCrateFactory | medieval, campsite, western (3) |
| LowPolyWaterSurfaceFactory | medieval, fishing (2) |
| LowPolyArchFactory | monastery, ruins (2) |
| LowPolyColumnFactory | monastery, ruins (2) |
| (others) | 1 |

**Implementation priority based on actual data**:
1. **LanternPost** (5/6 — exterior lighting is universal)
2. **Fence** (4/6 — second most universal)
3. **Barrel** (4/6)
4. **Crate** (3/6)
5. **WaterSurface** (2/6 but high narrative weight)
6. **Arch + Column** (2/6 each, often paired)
7. (then everything else)

This contradicts what I'd have guessed without the empirical attempts —
LanternPost was tier 1 in the original list but I'd have guessed Fence
was the single biggest unlock. Both matter, but lanterns appear in more
attempt categories.

### Imagined prompts (not yet built — same methodology applies)

The prompts below are reasoned about but not yet built via MCP. Each
gap list is from mental simulation; expect new gaps to surface when
they're actually attempted.

### Prompt 3 — "Wild West frontier town main street"

What I'd need:
- Saloon / bank / sheriff (longhouse + cottage variants) ✅
- A **boardwalk** along the buildings (raised wooden plank path) ❌
- **Hitching posts** in front of the saloon ❌
- A **water tower** on legs (parametric tower variant — partial ✅)
- **Wagons / carts** in the street ❌
- A **windmill** (vane on a tower) ❌
- **Fences** / corral railings ❌
- **Barrels** ❌
- **Tumbleweeds** (low-poly icosphere with material) ❌

Verdict: buildings ✅, transport + town infra ❌.

### Prompt 5 — "fantasy mountain monastery at sunset"

What I'd need:
- A **mountain** / cliff backdrop (procedural terrain) ❌
- The **monastery building** (longhouse + tower combo) ✅
- A **stone path** climbing to the entrance ❌
- **Stone steps** ❌
- **Statues** flanking the gate ❌
- **Prayer flags** / banners on poles ❌
- **Lanterns** / torches ❌
- **Stone pillars** / columns ❌

Verdict: building ✅, terrain + ritual props ❌.

### Prompt 4 — "lakeside fishing village"

What I'd need:
- Houses ✅
- **Lake / water surface** ❌
- **Pier / dock** (wooden plank platform on stilts) ❌
- **Boats** (small rowboat geometry) ❌
- **Fishing nets** drying on poles ❌
- **Fences** along the dock ❌
- **Barrels** / **crates** ❌
- **Lanterns** / lamp posts ❌

Verdict: houses ✅, water + boats + props ❌.

### Prompt 6 — "ancient ruins at the edge of a forest"


What I'd need:
- Trees ✅
- **Broken walls** (variant of LowPolyHouseFactory with wall_archetype="ruined"?) 🟡
- **Fallen pillars** (lying cylinders) ❌
- **Standing stones / monoliths** (cylindrical or rectangular vertical blocks — could be a Boulder variant) 🟡
- **Stone arches** / portal frames ❌
- **Overgrown vines** (texture/decal — out of v0 mesh scope) — skip
- **Cracked floor tiles** (low-poly disc subdivisions, out of scope) — skip

Verdict: variants of existing factories cover some; arches + monoliths missing.

---

## Cross-prompt frequency table

How often each missing-object class appeared in 6 prompts above:

| Object | Count | Prio |
|---|---|---|
| Fences / railings | 4 | **Tier 1** |
| Lanterns / lamp posts | 4 | **Tier 1** |
| Path / road / boardwalk | 4 | **Tier 1** |
| Barrels | 4 | **Tier 1** |
| Crates | 3 | **Tier 1** |
| Water surface | 3 | **Tier 1** |
| Bridge | 2 | Tier 2 |
| Boats / wagons / carts | 3 | Tier 2 |
| Signposts | 2 | Tier 2 |
| Statues / monoliths | 2 | Tier 2 |
| Campfire | 1 | Tier 3 |
| Tents | 2 | Tier 3 |
| Pier / dock | 1 | Tier 3 |
| Fishing nets / props | 1 | Tier 3 |
| Stone arches / portals | 1 | Tier 3 |
| Mountain / cliffs (terrain) | 1 | Tier 3 (terrain pipeline is its own thing) |
| Windmill | 1 | Tier 3 |
| Hitching posts | 1 | Tier 3 |

Tier 1 = appears in most prompts; should land first.

---

## Specs · Tier 1 (most-needed)

### `LowPolyFenceFactory`

A row of vertical posts connected by horizontal rails. Variations
cover everything from picket fences (yards) to corrals
(frontier-town) to stone walls (monastery).

```
fence_archetype : str = "picket"
                  Options: "picket", "post_and_rail", "stone_wall",
                           "wooden_plank"
length          : float = 6.0           m, total fence length
height          : float = 1.2           m
post_spacing    : float = 1.5           m, between posts
post_radius     : float = 0.05          m
n_rails         : int  = 2              horizontal rails (post_and_rail)
slat_density    : int  = 20             pickets per length (picket)
slat_width      : float = 0.08          m (picket / wooden_plank)
straight_or_curved : str = "straight"   "curved" wraps along an arc

wall_color      : str = "wood"          slot 0 (posts + rails / pickets)
accent_color    : str | None = None     slot 1 (top caps, optional)
```

Material slots: 1 (or 2 with caps).
Polycount: ~30 (picket short fence) to ~200 (long stone wall).
Implementation: per archetype, generate post grid + horizontal rails or
slats as small bmesh boxes; for stone_wall use a small sequence of
displaced cubes; for wooden_plank use 1×N strips.

### `LowPolyLanternPostFactory`

A vertical post with a lamp/lantern at the top. Variants cover wood
post, iron post, stone column with brazier.

```
lantern_archetype : str = "iron_post"
                  Options: "iron_post", "wooden_post", "stone_brazier",
                           "hanging_lantern" (no post; mount on building)
post_height       : float = 2.4
post_radius       : float = 0.06
lamp_size         : float = 0.35        m, top lamp box / glow
lamp_archetype    : str = "box"         "box", "globe", "torch"
emission_strength : float = 0.0         we ignore lighting in v0;
                                        emission saved for later

post_color   : str = "rust_metal"       slot 0 (post + cap)
glass_color  : str = "foliage_lemon"    slot 1 (lamp body — yellow glow)
```

Slots: 2.
Polycount: ~20–80.
Implementation: post = thin cylinder; lamp = small icosphere or cube;
brazier = wider hexagonal cup with a flame icosphere (orange).

### `LowPolyPathFactory`

A 2D ribbon of mesh that follows a curve, used as ground decoration
for paths, roads, boardwalks. Decals would do this better (and be
cheaper) but for v0 we need a real mesh because Maquette doesn't have
shader-graph painting yet.

```
path_archetype : str = "dirt"
                 Options: "dirt", "stone_paved", "wooden_boardwalk"
length         : float = 10.0           m (or pass control_points)
width          : float = 1.5            m
control_points : list[Vec2] | None      lets caller draw a winding path
slab_count     : int = 8                stone_paved tiles
plank_count    : int = 12               boardwalk planks
                                       (auto from length if None)

path_color : str = "ground_sand"        slot 0
edge_color : str | None = None          slot 1 (stone_paved edge tiles)
```

Slots: 1–2.
Polycount: ~10 (dirt) to ~80 (boardwalk).
Implementation: dirt = single quad strip with z=0.02; stone_paved =
discrete tiles with thin gaps; boardwalk = parallel planks raised on a
2-rail support with slight gaps between.

### `LowPolyBarrelFactory`

A wooden barrel — cylindrical body with banded staves, optionally on
its side. Common storage/decoration prop.

```
barrel_archetype : str = "wooden"
                   Options: "wooden", "metal_drum"
height           : float = 1.0          m
radius           : float = 0.4
n_staves         : int = 12             vertical staves (cylinder sides)
n_bands          : int = 2              horizontal hoops
on_its_side      : bool = False         lying down

body_color  : str = "wood"               slot 0
band_color  : str = "rust_metal"         slot 1
top_color   : str | None = None          slot 2 (lid; defaults to body)
```

Slots: 2–3.
Polycount: ~50 (12 staves × 2 caps + 2 hoops).
Implementation: cylinder with manual side faces (no closed top by
default for "open barrel" feel); hoops as torus rings or thin
cylinders ringing the body.

### `LowPolyCrateFactory`

A wooden cube crate — even simpler. Usually stacked.

```
crate_archetype : str = "wooden"
                   Options: "wooden", "metal", "fragile"
size            : float | tuple = 0.8   m, cube edge or (w, h, d)
plank_pattern   : bool = True           visible plank seams (wood)
edge_strapping  : bool = False          metal strapping at corners

body_color : str = "wood"
strap_color : str | None = None         slot 1 if strapping is on
```

Slots: 1–2.
Polycount: 6–30.
Implementation: cube; for plank_pattern, subdivide top face into ~3
strips and offset slightly; for strapping, add thin extruded edges.

### `LowPolyWaterSurfaceFactory`

Flat plane that reads as a still water surface. Strictly a static
plane in v0; ripples and reflection are shader / lighting concerns.

```
water_archetype : str = "still_lake"
                  Options: "still_lake", "stream", "puddle"
extent          : tuple[float, float] = (8, 6)    m × m for lakes
length, width   : floats for streams (long + narrow)
control_points  : list[Vec2] | None     optional path for streams
edge_lift       : float = 0.0           m, raise edges if you want
                                        a basin look

water_color : str = "water"             slot 0
```

Slots: 1.
Polycount: 1 (single quad) for the simplest case; higher if
control-point-curved.
Implementation: plane primitive; for stream, subdivide along length
and offset edges by control_points.

---

## Specs · Tier 2 (next)

### `LowPolyBridgeFactory`

A wooden plank bridge with handrails, spanning two endpoints.
Decorative — no actual physics.

```
bridge_archetype : str = "wooden_planks"
                   Options: "wooden_planks", "stone_arch", "rope_plank"
length           : float = 5.0
width            : float = 1.4
arch_height      : float = 0.4          rise at midspan
plank_count      : int = 12
has_railings     : bool = True
support_count    : int = 2              vertical posts under deck

deck_color    : str = "wood"
support_color : str = "rock_shadow"
rail_color    : str | None = None
```

Slots: 2–3.
Polycount: ~40–80.

### `LowPolyBoatFactory`

A small rowboat or fishing skiff — single hull mesh.

```
boat_archetype : str = "rowboat"
                 Options: "rowboat", "raft", "barge"
length         : float = 3.5
width          : float = 1.4
hull_height    : float = 0.5
n_seats        : int = 2
has_oars       : bool = True
has_mast       : bool = False           "barge" archetype

hull_color : str = "wood"
seat_color : str = "rock_pale"
sail_color : str = "stucco"             slot 2 if has_mast
```

Slots: 2–3.
Polycount: ~50.

### `LowPolySignpostFactory`

A vertical post with one or more horizontal arrow / sign boards,
optionally with text decals (skip for v0; placeholder geometry only).

```
signpost_archetype : str = "wooden_arrow"
                      Options: "wooden_arrow", "stone_marker",
                               "milestone"
height             : float = 2.2
n_signs            : int = 1            horizontal sign boards
sign_directions    : list[float] | None radians around vertical;
                                        random if None

post_color : str = "wood"
sign_color : str = "stucco"
```

Slots: 2.
Polycount: ~20.

### `LowPolyMonolithFactory`

A standing stone — cylindrical or rectangular vertical block. Could
be a Boulder variant but cleaner as its own factory because the
intent is different (architectural, not natural).

```
monolith_archetype : str = "rectangular"
                      Options: "rectangular", "cylindrical",
                               "obelisk"  (4-sided tapered)
height             : float = 3.0
base_size          : float = 0.6        m (square edge or radius)
top_size           : float = 0.4        m (obelisk taper)
n_sides            : int = 6            cylindrical only
weathering         : bool = True        slight random vertex displacement

stone_color : str = "rock_shadow"
```

Slots: 1.
Polycount: ~20–60.

---

## Specs · Tier 3 (specific scenes)

### `LowPolyCampfireFactory`

Stone ring + crossed logs. Optionally a flame icosphere on top.

```
ring_radius : float = 0.6
n_stones    : int = 8
log_count   : int = 4
log_length  : float = 0.8
has_flame   : bool = False              skip in v0; emission later

stone_color : str = "rock_shadow"
log_color   : str = "wood"
flame_color : str | None = "accent_red"
```

Slots: 2–3. Polycount: ~30.

### `LowPolyTentFactory`

Triangular-prism camping tent.

```
tent_archetype : str = "ridge"          "ridge" (A-frame), "round" (yurt)
length         : float = 2.5
width          : float = 1.8
height         : float = 1.4
has_door       : bool = True            open triangular flap

fabric_color : str = "rock_warm"
pole_color   : str = "rock_shadow"
```

Slots: 2. Polycount: ~10–20.

### `LowPolyPierFactory`

Wooden plank platform on stilts. Composite of post grid + plank deck.

```
length          : float = 6.0
width           : float = 2.0
deck_height     : float = 0.6
n_post_rows     : int = 4
plank_count     : int = 12
has_railings    : bool = True

deck_color    : str = "wood"
post_color    : str = "rock_shadow"
```

Slots: 2. Polycount: ~80.

### `LowPolyArchFactory`

Standalone stone archway — for portals, ruins, gateways.

```
arch_archetype : str = "round"
                  Options: "round", "pointed_gothic", "broken"
height         : float = 4.5
width          : float = 2.5
column_radius  : float = 0.4
keystone       : bool = True            top decorative keystone

stone_color   : str = "rock_pale"
keystone_color : str | None = "accent_red"
```

Slots: 1–2. Polycount: ~30.

### `LowPolyWindmillFactory`

Tower + 4-vane assembly. Could also be archetype of `LowPolyHouseFactory`
since the tower body is just a tall hipped-roof building, but the
vanes make it distinct enough to warrant its own factory.

```
tower_archetype : str = "stone"         "stone" or "wooden"
tower_height    : float = 7.0
tower_radius    : float = 1.6
vane_archetype  : str = "x4"            "x4" or "x6"
vane_length     : float = 4.0
vane_width      : float = 0.8
vane_rotation   : float = 0.0           degrees, for static animation

wall_color : str = "rock_pale"
roof_color : str = "rock_shadow"
vane_color : str = "wood"
```

Slots: 3. Polycount: ~60.

### `LowPolyStatueFactory`

A simple humanoid statue — torso + head + base. For monasteries,
cemeteries, town squares.

```
statue_archetype : str = "standing"      "standing", "kneeling",
                                         "obelisk_with_face"
height           : float = 2.4
base_size        : float = 0.8
pose_seed        : int                   minor proportion variations

stone_color    : str = "rock_pale"
weathering_color : str | None = None    slot 1 if dual-tone
```

Slots: 1–2. Polycount: ~50.

### `LowPolyLogFactory`

**(Discovered 2026-04-28 in campsite attempt.)** Long horizontal
fallen tree segment used as bench / decoration. Just a long tapered
cylinder with bark color.

```
log_archetype : str = "fallen"          "fallen" (lying), "stump", "hewn"
length        : float = 1.8
radius        : float = 0.18
taper         : float = 0.85            top radius = base * taper
n_sides       : int = 8
has_endcaps   : bool = True             rings show end grain
weathering    : bool = True             slight surface jitter

bark_color : str = "wood"
endcap_color : str | None = None         slot 1 (different end-grain tone)
```

Slots: 1–2. Polycount: ~20.
Implementation: cylinder via bmesh; rotate 90° around X for "fallen";
"stump" is a short vertical version; "hewn" is rectangular cut along
length.

### `LowPolyAxeStumpFactory`

**(Discovered 2026-04-28 in campsite attempt.)** A stump with an axe
embedded in the top — stylized "abandoned camp" tell. Composite of
log + axe head + axe handle.

```
stump_height    : float = 0.5
stump_radius    : float = 0.4
axe_handle_length : float = 0.7
axe_head_size   : float = 0.18
axe_lean        : float = 30.0          deg, axe sticks at angle

stump_color : str = "wood"
handle_color : str = "wood"
head_color  : str = "rust_metal"        slot 1
```

Slots: 2. Polycount: ~25.

### `LowPolyHitchingPostFactory`

Two short vertical posts with a horizontal rail between — for
hitching horses outside saloons. Trivially small, but distinct.
**Empirically confirmed** in Wild West attempt.

```
length     : float = 2.0
post_height : float = 1.2
rail_height : float = 0.9
n_rails    : int = 1                     1 or 2 stacked rails

wood_color : str = "wood"
```

Slots: 1. Polycount: ~10.

---

## Specs · Tier 4 (discovered in attempts 3–6)

Concise specs — same shape as Tiers 1–3, just shorter for second-pass
factories. Expand as they're implemented.

### `LowPolyBoardwalkFactory`

Raised wooden plank sidewalk in front of buildings. Frontier-town
staple.

```
length, width = 6.0, 1.6
height = 0.25                 raise off the dirt
plank_count = 14
post_count = 4                support posts under the deck
has_railings : bool = False

deck_color = "wood"; post_color = "rock_shadow"
```

Slots: 2. Polycount: ~40.

### `LowPolyWagonFactory`

Covered wagon / chuck wagon / cart. 4 wheels + box body + canopy
hoops.

```
wagon_archetype : str = "covered"      "covered", "cart", "chuck"
length = 2.5; width = 1.4; height = 1.4
has_canopy : bool = True               curved hoops + cloth
n_wheels = 4
wheel_radius = 0.45

body_color = "wood"
wheel_color = "rock_shadow"
canopy_color = "stucco"
```

Slots: 3. Polycount: ~80.

### `LowPolyTumbleweedFactory`

Big tangled dry-bush ball that rolls. Could be a `bush` archetype on
NativeLowPolyTreeFactory but the trunk is wrong; cleaner as its own.

```
radius = 0.6; n_clumps = 4               internal small icospheres
bumpiness = 0.2

color = "rock_warm"                     a warm tan
```

Slots: 1. Polycount: ~30.

### `LowPolyWaterTowerFactory`

Stilted tank — 4 legs supporting a cylindrical or conical tank with a
small roof. Common in westerns.

```
tank_archetype : str = "cylindrical"     "cylindrical", "conical"
tank_radius = 1.6; tank_height = 2.4
leg_height = 4.0; n_legs = 4
has_roof = True
ladder_visible : bool = True             single ladder strip

tank_color = "wood"; leg_color = "wood"; roof_color = "rock_shadow"
```

Slots: 2-3. Polycount: ~80.

### `LowPolyFishingNetFactory`

A drying net hung between two posts. Geometry: 2 posts + a low-poly
mesh "drape" between them.

```
length = 2.5; height = 1.4
post_radius = 0.05
mesh_density = "low"                     visible only as silhouette

post_color = "wood"; net_color = "stucco"
```

Slots: 2. Polycount: ~20.

### `LowPolyBuoyFactory`

Floating marker. Cone or cylinder with a top cap, sits on water
surface.

```
buoy_archetype : str = "cone"            "cone", "barrel"
size = 0.4

body_color = "accent_red"; cap_color = "stucco"
```

Slots: 2. Polycount: ~10.

### `LowPolyMountainFactory`

Procedural mountain backdrop — tall cone with horizontal banding +
optional snow cap. Already exists in spirit (we built Mt Mindolluin
for the Minas Tirith scene long ago); promote that into a factory.

```
height = 50.0; base_radius = 30.0
sides = 16; bands = 8
snow_threshold = 0.7                     fraction of height
ridge_amount = 0.13                      vertical-rib displacement amplitude

rock_color = "rock_cool"; snow_color = "stucco"
```

Slots: 2. Polycount: ~250.
Implementation note: Mt Mindolluin code in legacy citadel scene is
the exact algorithm; just port it.

### `LowPolyStonePathFactory`

Switchback stone steps for monastery / temple ascent. Could be
archetype of LowPolyPathFactory (`path_archetype="stone_steps"`) once
that lands.

### `LowPolyPrayerFlagFactory`

String of cloth squares hung between two posts. Five colored squares
in tibetan-flag order.

```
length = 4.0
flag_count = 5
flag_size = 0.4

post_color = "wood"
flag_colors : list[str] = ["accent_red", "foliage_apple", "foliage_amber",
                           "foliage_amethyst", "foliage_mint"]
```

Slots: 6 (one per flag color + posts). Polycount: ~25.

### `LowPolyColumnFactory`

Stone pillar — cylindrical with optional capital + base, optionally
broken / fallen. Distinct from Monolith because columns are
architectural elements (often paired, often supporting something).

```
column_archetype : str = "doric"          "doric", "ionic", "rough"
height = 4.0; radius = 0.4
n_sides = 12
has_capital = True; has_base = True
state : str = "upright"                   "upright", "fallen", "broken"

stone_color = "rock_pale"
```

Slots: 1-2. Polycount: ~40.

### `LowPolyBrazierFactory`

Fire bowl on a pedestal. Could be sub-archetype of LanternPost
(`lantern_archetype="brazier"`).

### `LowPolyBellFactory`

Bronze bell on a wooden frame. Two posts + crossbeam + bell.

```
bell_size = 0.8; frame_height = 2.2
clapper_visible : bool = False

bell_color = "rust_metal"; frame_color = "wood"
```

Slots: 2. Polycount: ~30.

### `LowPolyBrokenWallFactory`

Ruined wall fragment — a partial-height wall with jagged top edge.
Better than the "flat-roof short cottage" hack used in Attempt 6.

```
length = 4.0; height = 1.5            average; varies along length
thickness = 0.4
crumble_seed : int                    drives the jagged top profile
n_segments = 6                        horizontal segments with varying heights

stone_color = "rock_pale"
moss_color : str | None = "foliage_pine"   slot 1, optional
```

Slots: 1-2. Polycount: ~40.

### `LowPolyVineFactory`

Ivy / vines — a thin strip of leaf-cluster-blobs along a curve, used
to drape over walls and ruins.

```
length = 3.0
density = 12                          leaf clumps per unit
thickness = 0.15

leaf_color = "foliage_pine"
```

Slots: 1. Polycount: ~50.

### `LowPolyTombstoneFactory`

Standing stone marker — sub-archetype of `LowPolyMonolithFactory`
with `monolith_archetype="tombstone"` (smaller, often rounded top).
Won't need its own factory.

### `LowPolyAltarFactory`

Stone slab on stepped base. Sacrificial / ritual altar.

```
slab_w, slab_d, slab_h = 1.6, 0.8, 0.2
n_steps = 2; step_height = 0.25

stone_color = "rock_pale"
accent_color : str | None = "accent_red"   slot 1, blood/embers
```

Slots: 1-2. Polycount: ~30.

### `LowPolyRubbleFactory`

Pile of broken masonry chunks. Better as `LowPolyBoulderFactory`
archetype (`shape_archetype="masonry"`) — angular faces instead of
organic ones — than its own factory.

### `LowPolyWellFactory`

Two short vertical posts with a horizontal rail between — for
hitching horses outside saloons. Trivially small, but distinct.

```
length     : float = 2.0
post_height : float = 1.2
rail_height : float = 0.9
n_rails    : int = 1                     1 or 2 stacked rails

wood_color : str = "wood"
```

Slots: 1. Polycount: ~10.

### `LowPolyWellFactory`

A circular stone well with a wooden roof + bucket on a crank.

```
well_archetype : str = "stone_round"     "stone_round", "wooden_box"
radius         : float = 0.8
wall_height    : float = 0.7
has_roof       : bool = True
roof_height    : float = 1.2
has_bucket     : bool = True

stone_color : str = "rock_pale"
wood_color  : str = "wood"
roof_color  : str = "rock_shadow"
```

Slots: 3. Polycount: ~50.

---

## Engineering principles for the procedural bank

These conventions exist already in the boulder/tree/house factories
and should be preserved as we add the above:

1. **`LowPolyXxxFactory`** subclass of `infinigen.core.placement.factory.AssetFactory`.
2. **Constructor knobs only** — no globals, no UI, no operator
   dependencies. Headless-safe.
3. **Per-archetype default dict** at module top so `archetype="x"`
   sets a reasonable starting point without overriding explicit
   kwargs.
4. **Material slots** assigned in the bmesh / polygon stage; use
   `materials.apply_palette_slots` to wire palette keys; never
   call `materials.clear()`.
5. **Pre-allocate enough material slots** before setting
   `polygon.material_index` (Blender clamps invalid indexes to 0).
6. **Single mesh output** unless an asset truly needs separate
   objects (e.g. a windmill might not).
7. **Spawn-asset deletes the placeholder**, so `create_placeholder`
   returns a lightweight Empty and `create_asset` builds the real
   geometry from scratch.
8. **No bpy.ops** in the build path where avoidable — direct
   bmesh + mesh ops are headless-safe. Use
   `bpy.ops.object.modifier_apply` only with explicit selection,
   not `butil.apply_modifiers` (which has reference-invalidation
   issues).
9. **Polygon flat-shading** is the canonical Maquette material
   (smooth_foliage=False default). Smooth-shading is opt-in.

Each new factory should be **one atomic commit** with the spec it
implements referenced in the commit body.

## Suggested implementation order

1. `LowPolyFenceFactory` (Tier 1, 4-prompt occurrence)
2. `LowPolyBarrelFactory` (Tier 1, easy, looks great in scenes)
3. `LowPolyCrateFactory` (Tier 1, basically free after barrel)
4. `LowPolyLanternPostFactory` (Tier 1, adds verticality + lighting hint)
5. `LowPolyPathFactory` (Tier 1, harder — needs control points)
6. `LowPolyWaterSurfaceFactory` (Tier 1, single quad initially; scope creep risk)
7. `LowPolyBridgeFactory`
8. `LowPolySignpostFactory`
9. `LowPolyMonolithFactory`
10. ...continue with Tier 3 as scene prompts demand.
