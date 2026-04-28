"""Maquette pastel palette · Firewatch-inspired.

A small dictionary of named hex colors used to give every low-poly
asset a single solid material. The names describe INTENT rather than
hue — `rock_warm` not `#C97F4E` — so factories can route assets to
named slots without baking a specific hex into the wrapper.

Selection rationale:
  - Dusty, slightly desaturated tones — straight primaries read as
    children's-toy plastic at low poly. Pastels carry mood.
  - Two rock pairs (warm/cool, pale/shadow) so a scatter of boulders
    across a scene has natural variation without N materials.
  - Foliage stays muted / olive-green range; vivid forest greens
    fight Firewatch's atmospheric perspective.
  - Sky and water tones included for future use even though sky is
    out of v0 scope — keeps the palette reference centralized.

The palette is deliberately small (~12 entries). Adding many more
would dilute the recognizability of the look. If a future asset
needs a hue not represented here, the right move is usually to pick
the closest existing entry, not to add a 13th color.
"""

from __future__ import annotations


MAQUETTE_PALETTE: dict[str, str] = {
    # Rocks — pair warm/cool, pair pale/shadow so a scatter has variety.
    "rock_warm":    "#C97F4E",   # terracotta / canyon sandstone
    "rock_cool":    "#7E8590",   # slate grey-blue
    "rock_pale":    "#D7B98A",   # pale sandstone / bone
    "rock_shadow":  "#5C3A2E",   # deep oxide / underplane
    # Foliage — desaturated. Pine darker than bush.
    "foliage_pine": "#3D5A4A",
    "foliage_bush": "#7A8C5C",
    # Ground.
    "ground_sand":  "#D9B884",
    "ground_grass": "#8A9462",
    # Water.
    "water":        "#3D5C68",
    # Sky / atmosphere — for world-bg use, not assets.
    "sky_warm":     "#E89766",   # sunset
    "sky_cool":     "#7A6D8B",   # dusty lavender
    # Accent — for flags, hazards, the rare narrative pop.
    "accent_red":   "#A33E2E",
}


def hex_to_rgba(hex_color: str) -> tuple[float, float, float, float]:
    """Convert a `#RRGGBB` string to a linear-space RGBA tuple suitable for
    Principled BSDF Base Color. Applies a sRGB→linear gamma 2.2 approximation
    (matching the convention used elsewhere in this fork).
    """
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"hex must be #RRGGBB, got {hex_color!r}")
    rgb = tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    lin = tuple(c ** 2.2 for c in rgb)
    return (*lin, 1.0)


def get(name: str) -> str:
    """Return the hex string for a palette name. Raises KeyError if unknown
    (rather than silently picking a default, which would mask typos)."""
    return MAQUETTE_PALETTE[name]
