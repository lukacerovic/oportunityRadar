"""OpenRouter — paid-inference market evidence (DECISIONS.md 2026-07-24). Usage evidence.

Two observations per ``discover`` run, both keyless:

* ``or_model_listed`` — a model whose ``created`` falls in the window is now purchasable
  inference. The payload carries ``hugging_face_id`` so identity can attach the event to the
  model's existing HF entity (or, via its display name, to the ``web`` product entity an HN
  launch already minted — "Kimi K3" on OpenRouter lands on ``web:kimi-k3``).
* ``or_rankings`` — one event per (category, week, model) from the rankings endpoints: the
  weekly token count for chart-topping models. Sparse by construction (top-10 only), which is
  exactly the "is this actually being paid for?" flag we want on watchlist-scale models.

The rankings endpoints are unofficial (the public ``/api/v1/models`` carries no usage data) and
have churned before, so their fetch is best-effort per category: a dead category is skipped, the
model list still lands. ``track`` is empty — usage is only observable for leaderboard models, so
there is nothing to deep-poll per target.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from seismo.collectors.base import RateLimiter, RawEventDraft, TrackTarget, Window
from seismo.collectors.http import make_client

MODELS_URL = "https://openrouter.ai/api/v1/models"
RANKINGS_URL = "https://openrouter.ai/api/frontend/v1/rankings/{category}"
CATEGORIES = ("tools", "images")


class OpenRouterCollector:
    source = "openrouter"

    def __init__(self, *, client: httpx.Client | None = None, min_interval_s: float = 1.0):
        self._client = client or make_client()
        self._limiter = RateLimiter(min_interval_s)

    def discover(self, window: Window) -> list[RawEventDraft]:
        self._limiter.wait()
        resp = self._client.get(MODELS_URL)
        resp.raise_for_status()
        models: list[dict[str, Any]] = resp.json().get("data") or []

        # Rankings reference models by canonical_slug (id + release-date suffix) — index both.
        by_slug: dict[str, dict[str, Any]] = {}
        for m in models:
            for key in (m.get("id"), m.get("canonical_slug")):
                if key:
                    by_slug[str(key)] = m

        drafts = [
            self._model_draft(m, created)
            for m in models
            if (created := self._created_at(m)) and window.since <= created < window.until
        ]
        for category in CATEGORIES:
            drafts.extend(self._ranking_drafts(category, by_slug, window))
        return drafts

    def track(self, targets: list[TrackTarget], window: Window) -> list[RawEventDraft]:
        return []

    def _ranking_drafts(
        self, category: str, by_slug: dict[str, dict[str, Any]], window: Window
    ) -> list[RawEventDraft]:
        """Weekly token counts for one rankings category. Best-effort: the endpoint is
        unofficial, so a 404/transport error skips the category rather than failing the run."""
        self._limiter.wait()
        try:
            resp = self._client.get(RANKINGS_URL.format(category=category))
        except httpx.TransportError:
            return []
        if resp.status_code != 200:
            return []
        drafts: list[RawEventDraft] = []
        for point in resp.json().get("data") or []:
            day = str(point.get("x") or "")
            try:
                occurred = datetime.fromisoformat(day).replace(tzinfo=UTC)
            except ValueError:
                continue
            if not (window.since <= occurred < window.until):
                continue
            for slug, tokens in (point.get("ys") or {}).items():
                if slug == "Others":  # the chart's aggregate remainder bucket, not a model
                    continue
                # A ":free"-style variant slug shares its base model's identity metadata.
                meta = by_slug.get(str(slug)) or by_slug.get(str(slug).split(":", 1)[0], {})
                drafts.append(
                    RawEventDraft(
                        source="openrouter",
                        source_event_uid=f"or_rank:{category}:{day}:{slug}",
                        event_type="or_rankings",
                        occurred_at=occurred,
                        payload={
                            "model_id": str(slug),
                            "category": category,
                            "tokens": tokens,
                            # Carried so identity can anchor without a second fetch; a delisted
                            # model has no metadata and stays unowned context.
                            "name": meta.get("name"),
                            "hugging_face_id": meta.get("hugging_face_id"),
                        },
                    )
                )
        return drafts

    @staticmethod
    def _created_at(model: dict[str, Any]) -> datetime | None:
        try:
            return datetime.fromtimestamp(int(model["created"]), tz=UTC)
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _model_draft(model: dict[str, Any], occurred: datetime) -> RawEventDraft:
        return RawEventDraft(
            source="openrouter",
            source_event_uid=f"or_model:{model['id']}",
            event_type="or_model_listed",
            occurred_at=occurred,
            payload={
                "model_id": model["id"],
                "canonical_slug": model.get("canonical_slug"),
                "name": model.get("name"),
                "hugging_face_id": model.get("hugging_face_id"),
                "pricing": model.get("pricing") or {},
                "context_length": model.get("context_length"),
                "description": model.get("description"),
            },
        )
