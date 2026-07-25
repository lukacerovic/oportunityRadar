"""The council's deterministic aggregation rule, split into its own leaf module.

Pure function, zero dependencies on the LLM-provider chain — deliberately so. `council.py` (the
orchestrator) imports `run_brief`/`complete_council`, which transitively pull in the whole LLM
layer; the API only needs the majority-vote arithmetic to render `council_stance`, not any of that.
Importing `council.py` from `api/app.py` would load the entire checkpoint chain into the web server
process for the sake of 6 lines of `Counter` logic — this module is that logic, alone.
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

CouncilStance = Literal["adopt", "watch", "reject"]


def aggregate_stance(stances: list[CouncilStance]) -> str:
    """Deterministic majority vote — the ONLY aggregation step, never an LLM call. Returns the
    majority stance, or ``'split'`` when no stance holds a strict majority of the votes."""
    if not stances:
        return "split"
    counts = Counter(stances)
    top_stance, top_n = counts.most_common(1)[0]
    return top_stance if top_n > len(stances) / 2 else "split"
