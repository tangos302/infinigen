# Maquette terrain PBR textures

CC0 1K PBR sets from [Polyhaven](https://polyhaven.com/textures), shipped
with the repo so the realistic terrain shader doesn't depend on network
access at render time.

Multiple options per biome — `_pick_biome_sets(seed)` rolls one per
scene so two builds of the same prompt with different seeds use
different textures.

| biome  | available sets                                                                                                                                                                                                                  |
|--------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| grass  | [`aerial_grass_rock`](https://polyhaven.com/a/aerial_grass_rock), [`grass_path_2`](https://polyhaven.com/a/grass_path_2), [`forest_floor`](https://polyhaven.com/a/forest_floor)                                                |
| forest | [`forrest_ground_01`](https://polyhaven.com/a/forrest_ground_01), [`forrest_ground_03`](https://polyhaven.com/a/forrest_ground_03), [`brown_mud_leaves_01`](https://polyhaven.com/a/brown_mud_leaves_01)                        |
| rock   | [`aerial_rocks_02`](https://polyhaven.com/a/aerial_rocks_02), [`aerial_rocks_04`](https://polyhaven.com/a/aerial_rocks_04), [`rock_face_03`](https://polyhaven.com/a/rock_face_03), [`rocky_terrain_02`](https://polyhaven.com/a/rocky_terrain_02) |
| snow   | [`snow_02`](https://polyhaven.com/a/snow_02), [`snow_03`](https://polyhaven.com/a/snow_03)                                                                                                                                      |
| sand   | [`coast_sand_rocks_02`](https://polyhaven.com/a/coast_sand_rocks_02), [`aerial_beach_03`](https://polyhaven.com/a/aerial_beach_03), [`brown_mud_dry`](https://polyhaven.com/a/brown_mud_dry)                                    |

Suffixes: `_diff_1k.jpg` (sRGB diffuse), `_nor_gl_1k.jpg` (OpenGL-style
normal, non-color), `_rough_1k.jpg` (roughness, non-color).

## Re-downloading / adding more sets

Each set is one curl call:

```bash
NAME=aerial_rocks_02
for kind in diff nor_gl rough; do
  curl -fsSL -o "${NAME}_${kind}_1k.jpg" \
    "https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/${NAME}/${NAME}_${kind}_1k.jpg"
done
```

To add a new biome option, drop the three files here and append the
slug to `_BIOME_SETS_OPTIONS[biome]` in `terrain_textures.py`.

License: CC0 — no attribution required, unrestricted commercial use.
