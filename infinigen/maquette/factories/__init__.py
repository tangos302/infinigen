"""Maquette factory wrappers.

Each module here defines a `LowPolyXxxFactory` class that subclasses
the upstream `XxxFactory` from `infinigen.assets.objects.*`. The
upstream class is left untouched; the subclass overrides the
geometry-finalize phase to produce low-poly, faceted output.
"""

from .boulder import LowPolyBoulderFactory
from .tree import LowPolyTreeFactory

__all__ = ["LowPolyBoulderFactory", "LowPolyTreeFactory"]
