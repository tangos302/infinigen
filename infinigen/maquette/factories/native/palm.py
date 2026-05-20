"""Compatibility stub — re-exports from `palm_tree`.

Sonnet has been observed to write `from infinigen.maquette.factories.native.palm import LowPolyPalmTreeFactory`
when the canonical module is `palm_tree`. This stub keeps the LLM-authored
build.py working without a generation retry.
"""

from __future__ import annotations

from infinigen.maquette.factories.native.palm_tree import *  # noqa: F401,F403
from infinigen.maquette.factories.native.palm_tree import LowPolyPalmTreeFactory  # noqa: F401
