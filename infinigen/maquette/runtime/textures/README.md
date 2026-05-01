# Maquette terrain PBR textures

These are CC0 1K PBR sets from [Polyhaven](https://polyhaven.com/textures), shipped
with the repo so the realistic terrain shader doesn't depend on network access at
render time.

| biome  | source                                                           |
|--------|------------------------------------------------------------------|
| grass  | [`aerial_grass_rock`](https://polyhaven.com/a/aerial_grass_rock) |
| forest | [`forrest_ground_01`](https://polyhaven.com/a/forrest_ground_01) |
| rock   | [`aerial_rocks_02`](https://polyhaven.com/a/aerial_rocks_02)     |
| snow   | [`snow_02`](https://polyhaven.com/a/snow_02)                     |
| sand   | [`coast_sand_rocks_02`](https://polyhaven.com/a/coast_sand_rocks_02) |

Suffixes: `_diff_1k.jpg` (sRGB diffuse), `_nor_gl_1k.jpg` (OpenGL-style normal,
non-color), `_rough_1k.jpg` (roughness, non-color).

## Re-downloading

```bash
for name in aerial_grass_rock forrest_ground_01 aerial_rocks_02 snow_02 coast_sand_rocks_02; do
  for kind in diff nor_gl rough; do
    curl -fsSL -o "${name}_${kind}_1k.jpg" \
      "https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/${name}/${name}_${kind}_1k.jpg"
  done
done
```

License: CC0 — no attribution required, unrestricted commercial use.
