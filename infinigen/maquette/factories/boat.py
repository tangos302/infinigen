"""Compatibility re-export for generated Maquette scripts.

The canonical factory lives in ``infinigen.maquette.factories.native.boat``.
Some LLM-generated build scripts import the shorter legacy path
(``from infinigen.maquette.factories.boat import LowPolyBoatFactory``);
keep that path working so a good scene does not crash before Blender
even starts. Mirrors the ``palm.py`` / ``wagon.py`` compat shims.
"""

from infinigen.maquette.factories.native.boat import LowPolyBoatFactory

__all__ = ["LowPolyBoatFactory"]
