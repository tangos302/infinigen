"""Compatibility re-export for generated Maquette scripts.

The canonical factory lives in ``infinigen.maquette.factories.native.wagon``.
Some LLM-generated build scripts import the shorter legacy path; keep that
path working so a good scene does not fail before Blender starts.
"""

from infinigen.maquette.factories.native.wagon import LowPolyWagonFactory

__all__ = ["LowPolyWagonFactory"]
