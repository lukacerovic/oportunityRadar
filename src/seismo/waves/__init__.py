"""Wave Radar — convergence detection over a population of entities (``WAVE_PLAN.md``).

A peer of ``trajectory/`` and ``significance/``, not a subpackage of ``graph/``: ``graph/`` mints
edges, this consumes them. Nothing here calls an LLM (invariant 4) — a wave exists, is scored, and
renders before any model is involved.
"""

from __future__ import annotations

from seismo.waves.detect import WaveStats, run_waves
from seismo.waves.observers import run_observers
from seismo.waves.outcomes import run_outcomes

__all__ = ["WaveStats", "run_waves", "run_observers", "run_outcomes"]
