"""Shared HTTP client. Every non-authenticated source gets a descriptive UA with a contact
address (doc 03 §4.2 — arXiv and EDGAR require it in spirit and letter)."""

from __future__ import annotations

import httpx

from seismo import __version__

CONTACT = "nikola.bogdanovic.ssfon@gmail.com"
USER_AGENT = f"seismograph/{__version__} (+monitoring research; contact: {CONTACT})"


def make_client(timeout: float = 20.0) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        follow_redirects=True,
    )
