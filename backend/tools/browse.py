"""The `browse` category — the agent drives a real page instead of only reading one.

`pydantic_ai_harness`'s `PlaywrightBrowserToolset`: navigate, read the accessibility tree,
click, type, press keys, choose options, hover, wait, scroll, go back and forward, run
JavaScript, manage tabs, answer dialogs, and read the page's console and network log.

**This is not `web_fetch`, and the difference is what it is for.** Fetch renders a URL and
hands back its text — one page, no state, nothing to click. These tools keep a browser
open *across* calls and across turns, which is what a login, a multi-step form, or an app
that only exists after JavaScript runs actually needs. The instructions the capability
ships say the same thing to the model, so it reaches for the cheap tool first.

**The session is the conversation's, not the run's.** `PlaywrightBrowser` (the capability)
opens a browser when a run starts and closes it when the run ends; that lifecycle is
bypassed here in favour of `services/browser`'s conversation-scoped manager, so the page
the operator is looking at when a turn finishes is the page the next turn continues on.
What is used from the harness is the toolset alone — the eighteen tools over a session we
own. See `tools/rebound.py` for why the tools are *defined* by a template and *dispatched*
through a per-conversation instance.

**Degrades, never fails.** No container runtime, a browser that hasn't come up, or offline
mode having suspended it all mean there is nothing to attach to; the tools say so and the
model moves on, exactly as web fetch does under the same conditions.
"""

from __future__ import annotations

from pydantic_ai import AbstractToolset, RunContext
from pydantic_ai_harness.playwright import (
    EgressPolicy,
    PlaywrightBrowserSession,
    PlaywrightBrowserToolset,
)

from runs import BrowserLive
from services.browser import BrowserSessionManager

from .deps import RunDeps
from .rebound import ReboundToolset

#: The tools the category contributes, unprefixed — the harness's own set. Written out so
#: the namespaced names can be declared for offline mode and the vision gate without
#: constructing a toolset at import time; `tests/test_browse_tools.py` checks the literal
#: against the real toolset, so a harness rename fails there rather than silently
#: un-gating a tool.
TOOL_NAMES = frozenset(
    {
        "navigate",
        "snapshot",
        "click",
        "type_text",
        "press_key",
        "select_option",
        "hover",
        "wait_for",
        "screenshot",
        "get_text",
        "scroll",
        "go_back",
        "go_forward",
        "execute_js",
        "tabs",
        "handle_next_dialog",
        "console_messages",
        "network_requests",
    }
)

#: Every browse tool *is* the internet — there is no page to drive without it — so offline
#: mode withholds them all rather than offering the model tools that can only fail.
NETWORK_TOOLS = frozenset(f"browse_{name}" for name in TOOL_NAMES)

#: `screenshot` returns the image as `BinaryContent`, which only a vision model can read.
#: Declared here (the category that owns the tool) and applied by `services/tool_policy`.
VISION_TOOLS = frozenset({"browse_screenshot"})

_UNAVAILABLE = (
    "The browser is not available right now (it runs in a container, and offline mode "
    "shuts it down). Use web_fetch or web_search to read a page instead, or try again "
    "once the connection is back."
)


class BrowserToolset(ReboundToolset):
    """The harness browser tools, dispatched through the conversation's live session."""

    async def bind(self, name: str, ctx: RunContext[RunDeps]) -> AbstractToolset[RunDeps] | str:
        sessions = ctx.deps.caps.get_optional(BrowserSessionManager)
        if sessions is None:
            return _UNAVAILABLE
        key = ctx.deps.sandbox_key
        live = await sessions.acquire(key)
        if live is None:
            return _UNAVAILABLE
        # A reaped conversation can be re-attached under a *new* session; the cached
        # toolset would still be pointed at the dead one, so it is keyed by the session's
        # token rather than by the conversation.
        bound = self.cached(live.token, lambda: _toolset_for(live.session))
        # Announce the live browser once per run, so the panel opens the moment the agent
        # first touches a page rather than after the turn. Teardown has no run to ride on
        # (a reap happens between turns), so it is delivered on the stream socket instead
        # — see `routes/browser.py`.
        if live.token not in ctx.deps.announced_browsers:
            ctx.deps.announced_browsers.add(live.token)
            ctx.deps.run.emit(
                BrowserLive(
                    conversation_id=key,
                    url=f"/browser/stream/{live.token}",
                    page_url=live.page_url or None,
                )
            )
        return bound


def _toolset_for(session: PlaywrightBrowserSession) -> AbstractToolset[RunDeps]:
    return PlaywrightBrowserToolset[RunDeps](session=session)


def browse_toolset() -> AbstractToolset[RunDeps]:
    """The `browse` category, built once at app assembly and shared by every run.

    The template's session is never entered, so constructing it starts no browser and
    needs no endpoint — it exists only to answer `get_tools` with the same definitions
    every run is offered.
    """
    template = PlaywrightBrowserSession(policy=EgressPolicy(block_private_addresses=False))
    return BrowserToolset("browse", _toolset_for(template))
