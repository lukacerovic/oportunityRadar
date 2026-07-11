"""Hindcast validation harness (doc 11).

The production pipeline run over backfilled history at past ``as_of`` dates, graded by pinned,
executable assertions (DR-11.1/DR-11.2). Not a separate simulator — the same orchestrators, a
different data origin. See :mod:`seismo.hindcast.runner`.
"""

from seismo.hindcast.case import Case, load_case, load_case_by_name
from seismo.hindcast.runner import HindcastResult, run_hindcast

__all__ = ["Case", "load_case", "load_case_by_name", "HindcastResult", "run_hindcast"]
