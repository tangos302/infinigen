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
