"""Web search and fetch — the agent's window onto the open web.

Two capabilities over one operator-run search provider:

- **search** queries the configured SearXNG instance's JSON API and returns the
  hits (title, url, snippet).
- **fetch** retrieves a single URL directly and extracts its main content as
  Markdown — guarded against SSRF (the target host is re-validated on every
  redirect hop) and bounded by a timeout, a byte cap, and a redirect cap.

Both mark their results as untrusted (:func:`core.untrusted.wrap_untrusted`) before
they reach the model — web content is data, never instructions. The provider
catalog is owner-scoped and managed like the model registry (encrypted key seam,
``in_session`` writes). The service raises domain errors only; the tool layer
translates them into Pydantic AI ``ModelRetry`` (recoverable) or a degradation
message (terminal), keeping this service reusable by non-agent callers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx
import trafilatura
from sqlalchemy import Engine
from sqlmodel import Session, select

from core.db import in_session
from core.exceptions import DegradedCapabilityError, NotFoundError, WebFetchError
from core.ssrf import assert_public_url
from core.untrusted import wrap_untrusted
from core.vault import Vault
from models.search import SearchProvider

_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True)
class SearchResult:
    """One web search hit. ``snippet`` is untrusted-wrapped (the provider relays
    text from arbitrary pages); ``title``/``url`` are short structural metadata."""

    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class FetchedPage:
    """A fetched page's main content as Markdown, untrusted-wrapped."""

    url: str
    title: str | None
    content: str


class SearchService:
    """The web capability: a SearXNG-backed search plus a guarded direct fetch.

    ``http_client`` is the pooled outbound client (``follow_redirects=False`` so
    fetch controls redirects for per-hop SSRF re-validation); None ⇒ a transient
    client per call (the path tests take). The bounds default to the configured
    settings and are injected so tests can shrink them.
    """

    def __init__(
        self,
        engine: Engine,
        vault: Vault,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout_s: float = 15.0,
        max_bytes: int = 2_000_000,
        max_redirects: int = 5,
        result_limit: int = 10,
    ) -> None:
        self._engine = engine
        self._vault = vault
        self._http_client = http_client
        self._timeout_s = timeout_s
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._result_limit = result_limit

    # --- provider catalog -------------------------------------------------

    async def list_providers(self, owner_id: str) -> list[SearchProvider]:
        def work(session: Session) -> list[SearchProvider]:
            return list(
                session.exec(
                    select(SearchProvider)
                    .where(SearchProvider.owner_id == owner_id)
                    .order_by(SearchProvider.name)
                ).all()
            )

        return await in_session(self._engine, work)

    async def get_provider(self, owner_id: str, provider_id: str) -> SearchProvider:
        def work(session: Session) -> SearchProvider | None:
            provider = session.get(SearchProvider, provider_id)
            return provider if provider is not None and provider.owner_id == owner_id else None

        provider = await in_session(self._engine, work)
        if provider is None:
            raise NotFoundError(f"search provider {provider_id!r} not found")
        return provider

    async def create_provider(
        self,
        owner_id: str,
        *,
        name: str,
        base_url: str,
        enabled: bool = True,
        engines: list[str] | None = None,
        params: dict | None = None,
        api_key: str | None = None,
    ) -> SearchProvider:
        provider = SearchProvider(
            owner_id=owner_id,
            name=name,
            base_url=base_url,
            enabled=enabled,
            engines=engines or [],
            params=params or {},
            api_key_enc=self._vault.encrypt_str(api_key) if api_key else None,
        )

        def work(session: Session) -> SearchProvider:
            session.add(provider)
            session.flush()
            session.refresh(provider)
            return provider

        return await in_session(self._engine, work)

    async def update_provider(
        self, owner_id: str, provider_id: str, **changes: object
    ) -> SearchProvider:
        """Apply field changes. ``api_key`` (plaintext, or "" to clear) is sealed
        before storage; every other key maps straight onto the column."""
        await self.get_provider(owner_id, provider_id)  # ownership check

        def work(session: Session) -> SearchProvider:
            provider = session.get(SearchProvider, provider_id)
            assert provider is not None  # just confirmed it exists and is owned
            for key, value in changes.items():
                if key == "api_key":
                    provider.api_key_enc = self._vault.encrypt_str(str(value)) if value else None
                elif value is not None:
                    setattr(provider, key, value)
            provider.updated_at = datetime.now(UTC)
            session.add(provider)
            session.flush()
            session.refresh(provider)
            return provider

        return await in_session(self._engine, work)

    async def delete_provider(self, owner_id: str, provider_id: str) -> None:
        await self.get_provider(owner_id, provider_id)  # ownership check

        def work(session: Session) -> None:
            provider = session.get(SearchProvider, provider_id)
            if provider is not None:
                session.delete(provider)

        await in_session(self._engine, work)

    async def _active_provider(self, owner_id: str) -> SearchProvider:
        """The first enabled provider, else a degraded capability (no web search)."""
        providers = await self.list_providers(owner_id)
        active = next((p for p in providers if p.enabled), None)
        if active is None:
            raise DegradedCapabilityError("no web search provider configured")
        return active

    # --- search & fetch ---------------------------------------------------

    async def search(
        self, owner_id: str, query: str, *, limit: int | None = None
    ) -> list[SearchResult]:
        """Query the active SearXNG provider's JSON API. An empty result list is a
        valid answer (the model concludes, rather than looping); an unreachable
        provider or non-JSON response is a degraded capability."""
        provider = await self._active_provider(owner_id)
        limit = self._result_limit if limit is None else limit
        params: dict = {"q": query, "format": "json", **provider.params}
        if provider.engines:
            params["engines"] = ",".join(provider.engines)
        headers: dict = {}
        if provider.api_key_enc:
            headers["Authorization"] = f"Bearer {self._vault.decrypt_str(provider.api_key_enc)}"
        url = provider.base_url.rstrip("/") + "/search"

        client = self._http_client or httpx.AsyncClient()
        owns = self._http_client is None
        try:
            # No redirect-following: the provider answers /search?format=json
            # directly, and an unguarded redirect would be an SSRF hole (the fetch
            # path guards every hop; this path simply refuses to follow).
            resp = await client.get(
                url, params=params, headers=headers, timeout=self._timeout_s, follow_redirects=False
            )
        except httpx.HTTPError as exc:
            raise DegradedCapabilityError(f"search provider unreachable: {exc}") from exc
        finally:
            if owns:
                await client.aclose()
        if resp.status_code >= 400 or resp.is_redirect:
            raise DegradedCapabilityError(f"search provider returned HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise DegradedCapabilityError(
                "search provider did not return JSON (enable SearXNG's json format)"
            ) from exc
        if not isinstance(data, dict):
            raise DegradedCapabilityError("search provider returned an unexpected JSON shape")

        results = data.get("results") or []
        return [
            SearchResult(
                title=r.get("title") or "",
                url=r.get("url") or "",
                snippet=wrap_untrusted(r.get("content") or "", source=r.get("url")),
            )
            for r in results[:limit]
        ]

    async def fetch(self, owner_id: str, url: str) -> FetchedPage:
        """Fetch a single URL and extract its main content as Markdown. SSRF-guarded
        (re-checked on each redirect), timeout/byte/redirect bounded. Raises
        :class:`SSRFError` (refused) or :class:`WebFetchError` (unreadable)."""
        await assert_public_url(url)
        client = self._http_client or httpx.AsyncClient(follow_redirects=False)
        owns = self._http_client is None
        try:
            raw, final_url = await self._get_with_redirects(client, url)
        except httpx.HTTPError as exc:
            raise WebFetchError(f"could not fetch {url!r}: {exc}") from exc
        finally:
            if owns:
                await client.aclose()
        return await asyncio.to_thread(self._extract, final_url, raw)

    async def _get_with_redirects(
        self, client: httpx.AsyncClient, url: str
    ) -> tuple[bytes, str]:
        """Follow redirects manually, re-running the SSRF guard on every hop, and
        return the raw body (capped at ``max_bytes``) and the final URL. The body
        is left as bytes so the extractor can detect the page's own charset."""
        current = url
        for _ in range(self._max_redirects + 1):
            async with client.stream(
                "GET", current, timeout=self._timeout_s, follow_redirects=False
            ) as resp:
                if resp.status_code in _REDIRECT_STATUS:
                    location = resp.headers.get("location")
                    if not location:
                        raise WebFetchError(f"redirect without a location from {current!r}")
                    current = urljoin(current, location)
                    await assert_public_url(current)
                    continue
                if resp.status_code >= 400:
                    raise WebFetchError(f"{current!r} returned HTTP {resp.status_code}")
                # Fixed-size reads bound peak memory: stop the moment the cap is
                # reached so a huge (or decompression-bomb) body can't be buffered.
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= self._max_bytes:
                        break
                return b"".join(chunks)[: self._max_bytes], current
        raise WebFetchError(f"too many redirects fetching {url!r}")

    def _extract(self, url: str, raw: bytes) -> FetchedPage:
        # Parse once; trafilatura detects the charset from the raw bytes (HTTP
        # header / <meta> / BOM), avoiding a wrong-encoding decode and a second parse.
        tree = trafilatura.load_html(raw)
        if tree is None:
            raise WebFetchError(f"could not parse {url!r}")
        body = trafilatura.extract(
            tree, output_format="markdown", include_links=True, with_metadata=False
        )
        if not body:
            raise WebFetchError(f"no readable content at {url!r}")
        metadata = trafilatura.extract_metadata(tree)
        title = metadata.title if metadata is not None else None
        return FetchedPage(url=url, title=title, content=wrap_untrusted(body, source=url))
