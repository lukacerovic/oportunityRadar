"""Hugging Face via the public Hub API (doc 03 §2.4). Usage evidence (the 4th type — A-5).

Two birds, per §24.3:
- **createdAt** gives identity + the ``usable_artifact`` maturity rung (any ``hf`` event promotes
  it, see ``trajectory.ladder``), and is natively historical — the hindcast loader for a model's
  birth (``load_hf``) rides on it.
- **downloads** is the ``hf_downloads_30d`` metric (a rolling 30-day *level*, doc 06 §1 —
  ``track`` re-observes it; never diff it as a counter).

Auth is optional (``SEISMO_HF_TOKEN``) — the public API works unauthenticated at a lower rate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from seismo.collectors.base import RateLimiter, RawEventDraft, TrackTarget, Window
from seismo.collectors.http import make_client
from seismo.config import settings

MODELS_URL = "https://huggingface.co/api/models"
MODEL_URL = "https://huggingface.co/api/models/{model_id}"
MODEL_CARD_URL = "https://huggingface.co/{model_id}/raw/main/README.md"
MODEL_CARD_CAP = 6000  # keep a generous slice of the model card text

# Broad-and-shallow relevance for live discovery (doc 03 §2.4). The org-scoped hindcast path
# (fetch_by_author) is exempt — a case already pins the org it cares about.
RELEVANT_PIPELINES = {
    "text-generation",
    "text2text-generation",
    "feature-extraction",
    "sentence-similarity",
    "fill-mask",
    "question-answering",
    "summarization",
    "translation",
    "image-text-to-text",
    "automatic-speech-recognition",
}
KEYWORDS = {"llm", "agent", "rag", "instruct", "embedding", "reasoning", "moe"}
# The Hub creates thousands of models a day, and near-empty clones inherit ``text-generation``, so a
# pipeline tag alone is not signal. Discovery requires *traction* (real usage/attention) AND a
# relevant modality — the point of the usage evidence type is a model people actually pull.
DOWNLOADS_FLOOR = 1000
LIKES_FLOOR = 10
MAX_PAGES = 20  # cursor pages of 100; bounds a daily discovery window


class HuggingFaceCollector:
    source = "hf"

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.Client | None = None,
        min_interval_s: float = 0.5,
    ):
        self._token = token if token is not None else (settings.hf_token or None)
        self._client = client or make_client()
        self._limiter = RateLimiter(min_interval_s)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def discover(self, window: Window) -> list[RawEventDraft]:
        """Models *trending now* that were *created in the window* and are relevant (doc 03 §2.4).

        HF has no server-side date filter, and sorting by ``createdAt`` is self-defeating — the
        newest models (top of that sort) have the least usage, so a traction gate would reject
        them all. The usage signal we want is the inverse: scan the models trending now
        (``trendingScore`` desc) and keep the ones *born* in the window with real traction + a
        relevant modality — a young model people are already pulling. We follow the Hub's ``Link``
        cursor up to ``MAX_PAGES`` (bounded — trending tails off fast)."""
        drafts: list[RawEventDraft] = []
        url: str | None = MODELS_URL
        params: dict[str, str | int] | None = {
            "sort": "trendingScore",
            "direction": -1,
            "full": "true",
            "limit": 100,
        }
        for _ in range(MAX_PAGES):
            if url is None:
                break
            self._limiter.wait()
            resp = self._client.get(url, params=params, headers=self._headers())
            resp.raise_for_status()
            models = resp.json()
            if not models:
                break
            for model in models:
                occurred = _created_at(model)
                if occurred is None:
                    continue
                # trendingScore is not date-ordered, so no early stop — filter each by birth date.
                if window.since <= occurred < window.until and self._relevant(model):
                    drafts.append(self._discovery_draft(model, occurred))
            url = _next_link(resp)
            params = None  # the cursor URL already carries the query
        return drafts

    def fetch_by_author(self, authors: list[str]) -> list[RawEventDraft]:
        """Targeted fetch of an org's models — the hindcast seed path (§24.3, doc 11 §1).

        ``discover`` pages from the newest models and cannot reach an arbitrary historical window;
        a case, however, pins the org, so we list ``?author=<org>`` and keep each model's real
        ``createdAt`` so replay places its birth in history correctly."""
        drafts: list[RawEventDraft] = []
        for author in authors:
            self._limiter.wait()
            resp = self._client.get(
                MODELS_URL,
                params={"author": author, "full": "true", "limit": 1000},
                headers=self._headers(),
            )
            resp.raise_for_status()
            for model in resp.json():
                occurred = _created_at(model)
                if occurred is not None:
                    drafts.append(self._discovery_draft(model, occurred))
        return drafts

    def model_cards(
        self, targets: list[TrackTarget], window: Window | None = None
    ) -> list[RawEventDraft]:
        """Fetch each known model's README (its model card) as a ``model_readme`` enrichment event
        — the HF equivalent of repo READMEs (§16). Discovery stores only usage metadata, so without
        this HF models have no readable content to comprehend. Errors isolated per target: a gated
        / private / card-less model (401/403/404) is skipped, not fatal to the batch."""
        drafts: list[RawEventDraft] = []
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        for target in targets:
            self._limiter.wait()
            try:
                resp = self._client.get(
                    MODEL_CARD_URL.format(model_id=target.native_id), headers=headers
                )
            except httpx.TransportError:
                continue
            if resp.status_code >= 400:
                continue
            body = _strip_frontmatter(resp.text).strip()
            if body:
                drafts.append(self._card_draft(target.native_id, body))
        return drafts

    @staticmethod
    def _card_draft(model_id: str, body: str) -> RawEventDraft:
        return RawEventDraft(
            source="hf",
            source_event_uid=f"model_readme:{model_id}",
            event_type="model_readme",
            occurred_at=datetime.now(UTC),
            payload={"id": model_id, "text": body[:MODEL_CARD_CAP]},
        )

    def track(self, targets: list[TrackTarget], window: Window) -> list[RawEventDraft]:
        """Re-observe each known model's ``downloads`` as a ``model_snapshot`` (usage level).

        Errors are isolated per target exactly like the GitHub tracker: a deleted/gated model
        (404/401/451) or a transient disconnect skips that one target, never the batch."""
        drafts: list[RawEventDraft] = []
        for target in targets:
            self._limiter.wait()
            try:
                resp = self._client.get(
                    MODEL_URL.format(model_id=target.native_id), headers=self._headers()
                )
            except httpx.TransportError:
                continue
            if resp.status_code in (401, 404, 451):
                continue  # gone / gated / private — expected attrition
            resp.raise_for_status()
            drafts.append(self._snapshot_draft(resp.json()))
        return drafts

    @staticmethod
    def _relevant(model: dict[str, Any]) -> bool:
        has_traction = (model.get("downloads") or 0) >= DOWNLOADS_FLOOR or (
            model.get("likes") or 0
        ) >= LIKES_FLOOR
        if not has_traction:
            return False
        if (model.get("pipeline_tag") or "") in RELEVANT_PIPELINES:
            return True
        blob = " ".join(
            [str(model.get("id") or ""), " ".join(str(t) for t in (model.get("tags") or []))]
        ).lower()
        return any(k in blob for k in KEYWORDS)

    @staticmethod
    def _discovery_draft(model: dict[str, Any], occurred: datetime) -> RawEventDraft:
        model_id = str(model.get("id") or model.get("modelId") or "").lower()
        return RawEventDraft(
            source="hf",
            source_event_uid=f"model_discovered:{model_id}",
            event_type="model_discovered",
            occurred_at=occurred,
            payload=model,
        )

    @staticmethod
    def _snapshot_draft(model: dict[str, Any]) -> RawEventDraft:
        occurred = datetime.now(UTC)
        model_id = str(model.get("id") or model.get("modelId") or "").lower()
        return RawEventDraft(
            source="hf",
            source_event_uid=RawEventDraft.snapshot_uid(f"model:{model_id}", occurred),
            event_type="model_snapshot",
            occurred_at=occurred,
            payload={
                "id": model_id,
                "downloads": model.get("downloads"),
                "likes": model.get("likes"),
            },
        )


def _strip_frontmatter(md: str) -> str:
    """Drop a model card's leading YAML frontmatter (--- … ---) so only prose text is kept."""
    if md.startswith("---"):
        end = md.find("\n---", 3)
        if end != -1:
            return md[end + 4 :]
    return md


def _created_at(model: dict[str, Any]) -> datetime | None:
    raw = model.get("createdAt") or model.get("created_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _next_link(resp: httpx.Response) -> str | None:
    """The ``rel="next"`` cursor URL from the Hub's ``Link`` header (``None`` on the last page)."""
    link = resp.headers.get("Link") or resp.headers.get("link")
    if not link:
        return None
    for part in link.split(","):
        segments = part.split(";")
        if len(segments) < 2:
            continue
        if 'rel="next"' in segments[1]:
            return str(segments[0].strip().strip("<>"))
    return None
