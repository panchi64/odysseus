"""Browser control — the agent drives a real page, in a window the operator shares.

:class:`HostBrowser` is the one visible Chromium this app launches on the operator's
machine (with the SSRF proxy it is pointed at); :class:`BrowserSessionManager` gives each
conversation its own context on that browser — its own window, its own cookie jar — and
reaps the ones nobody is using.
"""

from .host import HostBrowser
from .live import ControlledBrowserSession, LiveBrowser
from .session import BrowserSessionManager

__all__ = [
    "BrowserSessionManager",
    "ControlledBrowserSession",
    "HostBrowser",
    "LiveBrowser",
]
