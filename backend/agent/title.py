"""Naming a fresh conversation — a fast, reasoning-off utility call.

After a brand-new conversation's first turn lands, the chassis asks the utility
model for a short descriptive title so the operator never has to name a thread.
The task is trivial, so the call is deliberately cheap and must never tax the
turn it follows: reasoning is disabled and the output is capped. The engine emits
the result as ``conversation.titled`` and persists it; the frontend reveals it
with a typing animation.

How reasoning is disabled is **not** decided here — it is provider-shaped and
lives in :mod:`services.reasoning`. The caller resolves the model and its
reasoning-off :class:`~pydantic_ai.settings.ModelSettings` together (the registry
does this) and hands both in, so this module stays free of per-lab levers and a
strict endpoint that has no off-switch simply reasons normally.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic_ai import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from .meta import make_utility_agent

logger = logging.getLogger(__name__)

_TITLE_INSTRUCTIONS = (
    "You name chat threads. Given the first exchange between a user and an "
    "assistant, reply with a short, specific title of 3-6 words that captures the "
    "topic in Title Case. Output only the title: no quotes, no surrounding "
    "punctuation, no preamble, no explanation."
)

# Output-capped base settings; the caller's reasoning-off settings are merged on
# top. The cap is small because a title is a handful of words — with thinking
# disabled the model spends its whole budget on the answer.
_BASE_SETTINGS: ModelSettings = {"max_tokens": 48, "temperature": 0.3}

# Trim the prompt/answer fed to the namer — the topic is in the opening, and a
# long body only slows the call without sharpening the title.
_EXCERPT = 600
_MAX_TITLE_LEN = 60

_TEXT_PARTS = frozenset({"TextPart"})
_USER_PARTS = frozenset({"UserPromptPart"})


def _part_text(message: ModelMessage, part_names: frozenset[str]) -> str:
    return " ".join(
        part.content
        for part in message.parts
        if type(part).__name__ in part_names and isinstance(getattr(part, "content", None), str)
    ).strip()


def first_user_text(messages: list[ModelMessage]) -> str:
    """The first user prompt in a history — the topic the thread is named for."""
    for message in messages:
        text = _part_text(message, _USER_PARTS)
        if text:
            return text
    return ""


def last_assistant_text(messages: list[ModelMessage]) -> str:
    """The latest assistant answer text in a history."""
    for message in reversed(messages):
        text = _part_text(message, _TEXT_PARTS)
        if text:
            return text
    return ""


def _clean(raw: str) -> str | None:
    """Sanitize the model's reply into a single-line title, or None if empty.

    Models tend to wrap titles in quotes, prepend ``Title:``, or add a trailing
    period; strip those so the stored/animated name is clean."""
    line = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
    line = line.strip("\"'`").strip()
    for prefix in ("title:", "title -", "thread:"):
        if line.lower().startswith(prefix):
            line = line[len(prefix) :].strip()
    line = line.rstrip(".").strip()
    if not line:
        return None
    return line[:_MAX_TITLE_LEN].strip()


async def generate_title(
    model: Model,
    prompt: str,
    answer: str,
    *,
    reasoning_off: ModelSettings | None = None,
    timeout_s: float | None = None,
) -> str | None:
    """Name a conversation from its first exchange, or None on any failure.

    Best-effort and isolated: titling is a cosmetic nicety, so a model error,
    timeout, or empty reply degrades to "no auto-title" rather than disturbing the
    turn that produced the answer. ``reasoning_off`` is merged over the base caps
    (its source — :mod:`services.reasoning` — owns the per-provider lever);
    ``timeout_s`` bounds how long the call may run so a slow utility model cannot
    hold the run open."""
    settings: ModelSettings = {**_BASE_SETTINGS, **(reasoning_off or {})}
    agent = make_utility_agent(model, output_type=str, instructions=_TITLE_INSTRUCTIONS)
    user = f"User:\n{prompt[:_EXCERPT]}\n\nAssistant:\n{answer[:_EXCERPT]}"
    try:
        run = agent.run(user, model_settings=settings)
        # asyncio.TimeoutError is an Exception subclass (caught below); CancelledError
        # is not, so a cancelled run still propagates rather than degrading to a title.
        result = await (asyncio.wait_for(run, timeout_s) if timeout_s else run)
    except Exception as exc:  # noqa: BLE001 — titling is best-effort, never fails a turn
        logger.warning("conversation title generation failed: %s", exc)
        return None
    return _clean(result.output)
