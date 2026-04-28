"""Maquette · low-poly Firewatch-styled fork of Infinigen factories.

This subpackage adds wrapper-style factories that delegate the
procedural-decision-tree logic to upstream Infinigen factories and
intercept the output to produce low-poly, faceted, Firewatch-style
geometry. No upstream `infinigen.assets` code is modified.

Branch policy and design intent are documented in MAQUETTE.md at the
repository root. v0 scope is geometry only — materials and lighting
are deferred.
"""

__version__ = "0.0.1"
