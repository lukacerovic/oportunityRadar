"""Hugging Face community client — a model's own discussion tab.

Reads ``/api/models/{id}/discussions`` (list) and ``/discussions/{num}`` (comment events).
Disjoint from ``collectors.hf``, which reads model metadata + the model card but never the
discussion threads. Domain-gated: only entities carrying an ``hf`` anchor are served. Auth is
optional (``SEISMO_HF_TOKEN``) — the public API works unauthenticated at a lower rate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from seismo.collectors.base import RateLimiter
from seismo.collectors.http import make_client
from seismo.community.relevance import CommunityThread, _int
from seismo.community.targets import CommunityTarget
from seismo.config import settings

LIST_URL = "https://huggingface.co/api/models/{model_id}/discussions"
ONE_URL = "https://huggingface.co/api/models/{model_id}/discussions/{num}"
WEB_URL = "https://huggingface.co/{model_id}/discussions/{num}"


class HuggingFaceCommunityClient:
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

    def applies_to(self, target: CommunityTarget) -> bool:
        return bool(target.anchors.get("hf"))

    def fetch_threads(
        self, target: CommunityTarget, queries: list[str], *, limit: int
    ) -> list[CommunityThread]:
        model_id = target.anchors.get("hf")
        if not model_id:
            return []
        self._limiter.wait()
        try:
            resp = self._client.get(
                LIST_URL.format(model_id=model_id), headers=self._headers()
            )
        except httpx.TransportError:
            return []
        if resp.status_code >= 400:
            return []  # gated / private / no discussions — expected attrition
        discussions = resp.json().get("discussions", [])
        return [self._thread(model_id, d) for d in discussions[:limit]]

    def comments(self, thread: CommunityThread, *, limit: int) -> list[str]:
        ref = thread.ref or {}
        model_id, num = ref.get("model_id"), ref.get("num")
        if not model_id or num is None:
            return []
        self._limiter.wait()
        try:
            resp = self._client.get(
                ONE_URL.format(model_id=model_id, num=num), headers=self._headers()
            )
        except httpx.TransportError:
            return []
        if resp.status_code >= 400:
            return []
        out: list[str] = []
        for event in resp.json().get("events", []):
            if event.get("type") != "comment":
                continue
            raw = ((event.get("data") or {}).get("latest") or {}).get("raw")
            body = (raw or "").strip()
            if body:
                out.append(body)
            if len(out) >= limit:
                break
        return out

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _thread(model_id: str, d: dict[str, Any]) -> CommunityThread:
        num = d.get("num")
        return CommunityThread(
            thread_id=f"hf:{model_id}#{num}",
            title=str(d.get("title") or ""),
            source="hf",
            channel="HF Discussions",
            url=WEB_URL.format(model_id=model_id, num=num),
            comment_count=_int(d.get("numComments")),
            created_at=_ts(d.get("createdAt")),
            matched_queries=[f"hf:{model_id}"],
            ref={"model_id": model_id, "num": num},
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers


def _ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None
