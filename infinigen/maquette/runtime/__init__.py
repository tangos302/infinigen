"""Runtime helpers usable from inside generated build scripts.

These modules import `bpy`, so they only work inside Blender. Don't
import them from the pipeline orchestrator (which runs in plain Python).
"""
