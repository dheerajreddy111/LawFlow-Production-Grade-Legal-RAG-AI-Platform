"""URL ingestion — fetch a legal page, strip boilerplate, return clean text.

Used by the ``POST /api/v1/documents/ingest-url`` endpoint and by any
future scheduled ingest job. Backed by:

- ``httpx`` (async)               for the actual fetch — same client
                                  the Anthropic/Groq SDKs already pull
                                  in, so no extra runtime cost.
- ``trafilatura``                 for legal-page extraction: drops
                                  navigation, ads, related-article
                                  blocks, comment sections, etc., and
                                  keeps only the main article text.

The pipeline keeps the original URL, fetched title and language as
metadata so retrieved chunks display proper citations and so a future
right-rail can show the source domain.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
import trafilatura
from trafilatura.settings import use_config

from app.integrations.lc import traced

logger = logging.getLogger(__name__)


# httpx defaults: explicit, conservative — legal sites are sometimes
# slow, and we want a clear failure rather than an indefinite hang.
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; LawFlow-Ingest/0.1; +https://lawflow.local)"
)
MAX_BYTES = 5 * 1024 * 1024  # 5 MB — refuse anything larger as a defensive cap


# trafilatura ships with sensible legal-favoured defaults; nudge it
# toward fewer false positives by disabling its built-in fallback to
# justext/readability (which can re-introduce nav blocks). We keep
# precision over recall — better to drop a small section than to
# include a "related stories" sidebar in a citation.
_TFL_CONFIG = use_config()
_TFL_CONFIG.set("DEFAULT", "EXTRACTION_TIMEOUT", "30")
_TFL_CONFIG.set("DEFAULT", "USE_FALLBACK", "off")
_TFL_CONFIG.set("DEFAULT", "MIN_OUTPUT_SIZE", "200")


@dataclass
class URLIngestResult:
    """Output of :func:`fetch_url`. Maps cleanly into ``IngestResult``."""

    url: str
    title: str | None
    text: str
    language: str | None = None
    fetched_bytes: int = 0
    content_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class URLIngestionError(Exception):
    """Base class for URL ingestion failures (caught by the endpoint)."""


class URLFetchError(URLIngestionError):
    """Network or HTTP failure while fetching the URL."""


class URLTooLargeError(URLIngestionError):
    def __init__(self, size: int) -> None:
        super().__init__(
            f"Fetched body of {size:,} bytes exceeds {MAX_BYTES // (1024 * 1024)} MB cap"
        )
        self.size = size


class URLExtractionError(URLIngestionError):
    """Trafilatura could not extract usable text from the page."""


@traced(name="ingestion.fetch_url", run_type="chain")
async def fetch_url(
    url: str,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    user_agent: str = DEFAULT_USER_AGENT,
) -> URLIngestResult:
    """Fetch ``url`` and return cleanly-extracted body text + metadata.

    Raises a subclass of :class:`URLIngestionError` on failure.
    """
    headers = {"User-Agent": user_agent}

    try:
        async with httpx.AsyncClient(
            timeout=timeout_s, follow_redirects=True, headers=headers
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:  # noqa: BLE001 — boundary
        logger.warning("URL fetch failed: %s (%s)", url, exc)
        raise URLFetchError(f"Failed to fetch {url}: {exc}") from exc

    body = resp.content
    if len(body) > MAX_BYTES:
        raise URLTooLargeError(len(body))

    content_type = resp.headers.get("content-type", "") or None

    # Trafilatura is sync + CPU-bound; offload to a worker thread.
    import asyncio

    extracted = await asyncio.to_thread(_extract_sync, body, url)

    if not extracted["text"] or len(extracted["text"]) < 100:
        raise URLExtractionError(
            f"No usable article text extracted from {url}. The page may be "
            "JavaScript-rendered or behind a login wall."
        )

    return URLIngestResult(
        url=str(resp.url),
        title=extracted.get("title"),
        text=extracted["text"],
        language=extracted.get("language"),
        fetched_bytes=len(body),
        content_type=content_type,
        metadata={
            "author": extracted.get("author"),
            "date": extracted.get("date"),
            "sitename": extracted.get("sitename"),
            "categories": extracted.get("categories"),
            "tags": extracted.get("tags"),
            "final_url": str(resp.url),
        },
    )


def _extract_sync(body: bytes, url: str) -> dict[str, Any]:
    """Run trafilatura over a raw HTML body, return text + metadata."""
    extracted_text = trafilatura.extract(
        body,
        url=url,
        output_format="txt",
        include_comments=False,
        include_tables=True,
        favor_precision=True,
        config=_TFL_CONFIG,
    ) or ""

    # Companion metadata pass (title, language, date, …).
    meta = trafilatura.extract_metadata(body, default_url=url)
    meta_dict: dict[str, Any] = {}
    if meta is not None:
        meta_dict = {
            "title": getattr(meta, "title", None),
            "author": getattr(meta, "author", None),
            "date": getattr(meta, "date", None),
            "sitename": getattr(meta, "sitename", None),
            "language": getattr(meta, "language", None)
            or getattr(meta, "lang", None),
            "categories": getattr(meta, "categories", None),
            "tags": getattr(meta, "tags", None),
        }
    meta_dict["text"] = extracted_text
    return meta_dict
