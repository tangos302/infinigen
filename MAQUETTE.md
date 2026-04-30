# Maquette · Infinigen branch

Experimental low-poly fork of [Infinigen](https://github.com/princeton-vl/infinigen).

## Goal

Bend Infinigen's procedural decision tree (which assets, where they go,
how they vary) into producing **low-poly, Firewatch-style** meshes
instead of photoreal multi-million-poly assets.

A successful Maquette asset is a few hundred to a few thousand
triangles, faceted, no smooth shading, silhouette-readable at thumbnail
size. Quality target is "good enough", not perfect.

## v0 scope (today)

**In:**
- Geometry. Mesh complexity, shape, silhouette.
- One factory at a time, starting with `BoulderFactory`.
- Atomic commits — one knob, one rename, one new option per commit.

**Out (intentionally, for v0):**
- Materials. We will eventually have **one** Principled BSDF +
  pastel-Firewatch-style color palette, applied by object class. Today:
  ignore.
- Lighting / world / atmosphere.
- Asset-bank / scatter / scene-composition logic.
- Performance.

## Why a `maquette/` branch on this fork

- `main` tracks `upstream/main` from princeton-vl. We don't want the
  experiment to diverge `main`; pulling fresh upstream stays trivial.
- The `maquette` branch starts from a pristine `upstream/main` snapshot
  and has its own commit history. If a change is wrong, `git revert` it
  individually; if the whole experiment is abandoned, `main` is
  untouched.

## Companion repo

The Maquette MCP server / addon lives at
`tangos302/songe-blender-mcp` on the `maquette` branch under
`maquette_mcp/`. The two are co-developed.

## Conventions

- One feature → one commit. Commit message starts with the area:
  `boulder:`, `tree:`, `placement:`, `materials:`, etc.
- New low-poly variants are added as **opt-in flags** (e.g.
  `BoulderFactory(factory_seed=42, low_poly=True)`), not silent
  replacements of upstream behavior. That way `low_poly=False` defaults
  preserve photoreal behavior, and reverts are mechanical.

## Dev environment — opening .blend files in Blender on WSL2

WSLg ships a broken EGL/GLX path; the naive `blender file.blend`
crashes immediately with `EGL Error (0x3009): EGL_BAD_MATCH`. The
upstream issue is tracked in
[Blender 115483](https://projects.blender.org/blender/blender/issues/115483)
and [Blender 126119](https://projects.blender.org/blender/blender/issues/126119).

**Working recipe** (verified Blender 5.1.0 + WSLg, Apr 2026):

```bash
WAYLAND_DISPLAY="" \
  LIBGL_ALWAYS_SOFTWARE=1 \
  GALLIUM_DRIVER=llvmpipe \
  /home/tang/blender-5.1.0-linux-x64/blender path/to/scene.blend &
```

What each var does:

- `WAYLAND_DISPLAY=""` — set to empty string (NOT unset). Blender's
  GHOST detects WSLg's Wayland session even without
  `$WAYLAND_DISPLAY` set; explicitly empty disables the Wayland
  backend so it falls through to X11 (Xwayland).
- `LIBGL_ALWAYS_SOFTWARE=1` + `GALLIUM_DRIVER=llvmpipe` — force
  Mesa's software rasterizer. WSLg's hardware GLX exposes incomplete
  FBConfigs (`GLXBadFBConfig` errors) so software rendering
  sidesteps it. Viewport will be slower than native, but it opens.

**What does NOT work**:

- Plain `blender file.blend` → `EGL_BAD_MATCH`.
- `unset WAYLAND_DISPLAY` (env-removed) — GHOST still picks Wayland;
  same crash.
- `--gpu-backend opengl` — that's the only available backend on
  Linux; doesn't change anything.
- `XDG_SESSION_TYPE=x11` alone — Blender's GHOST ignores it.
- `EGL_PLATFORM=x11` — crashes earlier in init.
- `blender-softwaregl` shim — uses Mesa-side libs but doesn't disable
  Wayland; still hits EGL_BAD_MATCH.

The combo above is the minimum that works. If you also want the
Blender MCP path (open from a script via
`bpy.ops.wm.open_mainfile(...)`), that requires a separate running
Blender instance with the `blender_mcp_addon` loaded — the foundation
addon is at `~/blender-mcp-foundation/`.
