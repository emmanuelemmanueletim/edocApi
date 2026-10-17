"""Restrictive resource fetcher for untrusted HTML to PDF conversion."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def blocked_url_fetcher(url: str) -> dict[str, Any]:
    """Reject all linked resources, including file and network URLs."""
    parsed = urlparse(url)
    raise ValueError(f"External and local resources are blocked during PDF rendering: {parsed.scheme or 'unknown'}")
