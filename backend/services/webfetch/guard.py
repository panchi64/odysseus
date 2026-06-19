"""Per-request SSRF guard for the headless browser.

A browser fetch fans out into many outbound requests — the main document, its
redirects, and every subresource. Each is a request that, unchecked, could reach the
loopback interface, the private LAN, or the cloud metadata endpoint. This installs a
``page.route`` handler that re-runs :func:`core.ssrf.assert_public_url` on every http(s)
request and aborts any that resolve to a non-public address — the same policy the old
manual redirect loop enforced, now extended to subresources too.

In-memory schemes (``data:``/``blob:``/``about:``) are not network egress and are
allowed; ``assert_public_url`` itself refuses any other non-http(s) scheme (``file:``,
``chrome:``, …), so those abort.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from playwright.async_api import Route

from core.exceptions import SSRFError
from core.ssrf import assert_public_url

# Resources that never carry the page's text — dropped when block_media is on, both for
# speed and to shrink the SSRF surface.
_HEAVY_RESOURCES = frozenset({"image", "media", "font"})
# In-memory, non-network schemes — legitimate page resources, not an egress vector.
_INERT_SCHEMES = frozenset({"data", "blob", "about"})


class RequestGuard:
    """One per fetch. Records whether a **main-frame navigation** was SSRF-blocked so the
    fetcher can tell an open-redirect refusal (hard ``SSRFError``) from a generic load
    failure (recoverable ``WebFetchError``)."""

    def __init__(self, *, block_media: bool) -> None:
        self._block_media = block_media
        self.blocked_navigation: str | None = None

    async def handle(self, route: Route) -> None:
        request = route.request
        abort = False
        if self._block_media and request.resource_type in _HEAVY_RESOURCES:
            abort = True
        elif urlsplit(request.url).scheme not in _INERT_SCHEMES:
            try:
                await assert_public_url(request.url)
            except SSRFError:
                abort = True
                if _is_main_navigation(request):
                    self.blocked_navigation = request.url
        try:
            await (route.abort() if abort else route.continue_())
        except Exception:
            # The page/context may have torn down mid-flight (we close it as soon as the
            # content is captured); a route we can no longer act on is nothing to do.
            pass


def _is_main_navigation(request) -> bool:
    """Whether ``request`` is the top-level document navigation. Frame access can raise on
    a frame detached mid-flight — treat any failure as 'not the main nav' so the route is
    still resolved (an unhandled error in a route handler leaves the request hanging)."""
    try:
        return request.is_navigation_request() and request.frame.parent_frame is None
    except Exception:
        return False
