"""Browser control — the agent drives a real page, and the operator watches it.

:class:`BrowserSessionManager` keeps one live browser per conversation (attached to the
container Chromium web fetch already runs); :class:`Screencast` streams what that browser
shows so the panel beside the chat is the page itself rather than a log of clicks.
"""

from .screencast import Frame, Screencast
from .session import BrowserSessionManager, ControlledBrowserSession, LiveBrowser

__all__ = [
    "BrowserSessionManager",
    "ControlledBrowserSession",
    "Frame",
    "LiveBrowser",
    "Screencast",
]
