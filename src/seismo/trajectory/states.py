"""Momentum state machine (doc 06 §4) with hysteresis (DR-06.2) and cold-start warm-up (doc 14 §5).

Raw scores flap; states must not — the reader is a human. So a *raw tier* is computed from each
day's inputs (velocity percentile ``P``, breadth ``B``, promotions-in-30d, activity), then a
committed state is derived with hysteresis: **promotion needs the entry condition held 2
consecutive days; demotion needs the exit condition 7 consecutive days.** ``fading`` is the one
special exit (was ≥ simmering, now ``P`` below the fade floor for 14 days *or* inactive 30 days).

During cold start a thin cohort can't be trusted, so a day whose cohort is provisional (doc 14 §5)
has its **emitted** state capped at ``COHORT_WARMUP_STATE_CAP`` (``simmering``) — the percentile is
still recorded and audited (``inputs.provisional``/``cohort_n``), the machine just may not
manufacture a breakout from three data points. Hysteresis runs on the true tier underneath; only
the label is capped.

The whole replay is a pure function of events ≤ ``as_of`` (doc 06 §5): it recomputes from each
entity's first day, so it never depends on previously-written rows and is identical on re-run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from seismo.config import settings
from seismo.trajectory.velocity import DaySignal

# tier ordering; fading is a labelled overlay, not a tier.
STATES = ("dormant", "simmering", "accelerating", "breakout")
_TIER = {name: i for i, name in enumerate(STATES)}
PROMO_WINDOW_DAYS = 30


@dataclass
class DayState:
    state: str
    score: float
    inputs: dict[str, Any]


def raw_tier(sig: DaySignal, promo_30d: int, active: bool) -> int:
    """Highest tier whose entry condition holds today, ignoring hysteresis (doc 06 §4)."""
    if not active:
        return _TIER["dormant"]
    tier = _TIER["dormant"]
    if sig.count_60 >= 1:
        tier = _TIER["simmering"]
    if sig.count_80 >= 2 or (promo_30d >= 1 and sig.count_60 >= 1):
        tier = _TIER["accelerating"]
    if promo_30d >= 2 or (sig.count_95 >= 1 and sig.breadth >= settings.breakout_min_breadth):
        tier = _TIER["breakout"]
    return tier


def replay(
    start_day: date,
    end_day: date,
    signals: dict[date, DaySignal],
    event_days: list[date],
    promotion_days: list[date],
) -> dict[date, DayState]:
    """Run the hysteresis machine day-by-day over ``[start_day, end_day]`` and return one committed
    :class:`DayState` per day. ``event_days``/``promotion_days`` are sorted date lists used for the
    activity and promotion-count inputs."""
    promote_hold = settings.momentum_promote_hold_days
    demote_hold = settings.momentum_demote_hold_days
    fade_hold = settings.momentum_fade_hold_days
    active_days = settings.momentum_active_days
    fade_inactive = settings.momentum_fade_inactive_days
    cap_tier = _TIER.get(settings.cohort_warmup_state_cap, _TIER["simmering"])
    fade_floor = settings.momentum_p_fade

    zero = DaySignal()
    raw_hist: list[int] = []
    p_hist: list[float] = []
    tier = 0
    peaked = False
    out: dict[date, DayState] = {}

    day = start_day
    while day <= end_day:
        sig = signals.get(day, zero)
        active = _within(event_days, day, active_days)
        promo_30d = _count_within(promotion_days, day, PROMO_WINDOW_DAYS)
        r = raw_tier(sig, promo_30d, active)
        raw_hist.append(r)
        p_hist.append(sig.p)

        # Promotion: entry condition for a higher tier held for the whole promote-hold window.
        if len(raw_hist) >= promote_hold:
            sustained = min(raw_hist[-promote_hold:])
            if sustained > tier:
                tier = sustained
        # Demotion: exit condition (raw below current tier) held for the whole demote-hold window.
        if tier > 0 and len(raw_hist) >= demote_hold:
            best = max(raw_hist[-demote_hold:])
            if best < tier:
                tier = best
        if tier >= _TIER["simmering"]:
            peaked = True

        # Fading overlay: a once-warm entity decaying by velocity or by inactivity.
        fade_velocity = len(p_hist) >= fade_hold and all(
            p < fade_floor for p in p_hist[-fade_hold:]
        )
        fade_inactivity = not _within(event_days, day, fade_inactive)
        fading = peaked and tier == 0 and (fade_velocity or fade_inactivity)

        emitted_tier = tier
        if sig.provisional and emitted_tier > cap_tier:
            emitted_tier = cap_tier
        state = "fading" if fading else STATES[emitted_tier]

        out[day] = DayState(
            state=state,
            score=sig.p,
            inputs={
                "P": round(sig.p, 4),
                "breadth": sig.breadth,
                "promo_30d": promo_30d,
                "active": active,
                "raw_tier": r,
                "smoothed_tier": tier,
                "count_60": sig.count_60,
                "count_80": sig.count_80,
                "count_95": sig.count_95,
                "provisional": sig.provisional,
                "cohort_n": sig.cohort_n,
                "cohort_key": sig.cohort_key,
            },
        )
        day += timedelta(days=1)
    return out


def _within(sorted_days: list[date], day: date, window: int) -> bool:
    """True if any date in ``sorted_days`` lies in ``(day - window, day]``."""
    lo = day - timedelta(days=window)
    for d in sorted_days:
        if lo < d <= day:
            return True
        if d > day:
            break
    return False


def _count_within(sorted_days: list[date], day: date, window: int) -> int:
    lo = day - timedelta(days=window)
    return sum(1 for d in sorted_days if lo < d <= day)
