"""Suspending a turn on the operator — the payload and the park itself.

A turn that reaches a call nobody has authorised does not fail and does not guess: it
*stops*, with everything needed to carry on later held on the run. That continuation is
:class:`ParkedTurn`, and :func:`park_for_approval` is the one place it is built.

**Why a payload rather than a re-run.** Pydantic AI ends the turn with
``DeferredToolRequests`` *without executing* the sensitive call, so the agent, the message
history and the deferred requests are all still in hand. Keeping them means a resume
continues the same turn — same agent, same tools, same history — instead of replaying a
prompt against whatever the world looks like when the operator finally answers. Every
field on the payload exists because re-deriving it on resume would be a second, disagreeing
source for a fact the parked turn already settled.

**Why the notify happens before the park.** ``RunRegistry.cancel`` reads
``awaiting_input`` as "the task has already fully exited" and skips its hard-cancel path on
that assumption. Anything that awaits *after* ``run.park(...)`` would break it, so the one
await this module does before parking is deliberately ordered ahead of it.

The rules deciding which calls get here at all are ``gating.py``'s; this module only knows
what to do once a call needs the operator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    ModelMessage,
    ToolApproved,
    ToolDenied,
)

from runs import ApprovalRequired, Run
from services.conversations import ConversationBinding, ConversationStore
from services.notifications import NotificationService

from .naming import TitleContext, approval_conversation_title

logger = logging.getLogger(__name__)

# A stateless turn's workspace binding: an unfiled Normal thread. The conservative
# default — Normal never reaches the host — so a caller that forgets to resolve one
# cannot accidentally hand a run the operator's own files.
DEFAULT_BINDING = ConversationBinding()


@dataclass
class ParkedTurn:
    """The continuation of a run parked awaiting approval. Opaque to the
    substrate; held on ``run.parked_payload`` and consumed by the approve route."""

    agent: Agent
    message_history: list[ModelMessage]
    requests: DeferredToolRequests
    announced: set[str] = field(default_factory=set)
    # Deferred calls that never reached the operator: auto-approved by an active
    # conversation grant, or refused outright by the thread's permission level. Not
    # surfaced (no approval.required event for them) but merged back into the resume's
    # decisions so the single DeferredToolResults still covers every deferred call.
    settled: dict[str, ToolApproved | ToolDenied] = field(default_factory=dict)
    # Persistence context, attached by the orchestrator: the conversation and
    # the index from which messages are still unpersisted (so a resume records
    # the parked turn's messages too, once it finally completes).
    conversation_id: str | None = None
    persist_from: int = 0
    # When a *verifier* correction is what parked, the [start, end] message range
    # to drop on the eventual persist (the rejected answer + the synthetic nudge),
    # so the resume records a clean history too.
    clean_drop: tuple[int, int] | None = None
    # Auto-title context, carried so a first turn that parked for approval is still
    # named once it resumes and completes (titling lives at the shared finalize
    # point, not only in the initial chat turn). None ⇒ don't title on resume.
    title: TitleContext | None = None
    # Attachment context, carried so a turn that parked for approval still installs its
    # durable attachment markers (and stamps the ids) when the resume finally persists it —
    # keeping replayed history marker-only just like a direct turn.
    attachment_ids: list[str] = field(default_factory=list)
    persisted: list | None = None
    # The turn's model-request budget (the operator's setting, else the config default),
    # carried so the resume continues under the same ceiling the original turn ran with
    # rather than silently reverting to the default. None ⇒ resolve from config.
    request_limit: int | None = None
    # The thread's binding, carried rather than re-read on resume. A resume that
    # defaulted it to Normal would hand a parked code turn a different filesystem than the
    # one it parked in — and the permission level rides along for the same reason it is
    # read once per turn rather than per call: the operator may raise the level while this
    # is parked, and a call they are about to approve must be judged by the rules that
    # deferred it, not by rules that arrived afterwards.
    binding: ConversationBinding = field(default_factory=ConversationBinding)
    # Whether the model this turn runs on can read an image, carried for the same reason
    # `binding` is: the resume must offer the tools the parked turn was offered. Re-reading
    # it would resolve whatever is bound *now*, which need not be the model the parked
    # agent still holds — so a re-read would be a second, disagreeing source for one fact.
    vision: bool = True


def summarize_call(name: str, args: dict[str, Any]) -> str:
    """The one-line rendering of a call the operator is being asked about."""
    rendered = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return f"{name}({rendered})"


async def park_for_approval(
    run: Run,
    agent: Agent,
    messages: list[ModelMessage],
    requests: DeferredToolRequests,
    announced: set[str],
    *,
    settled: dict[str, ToolApproved | ToolDenied] | None = None,
    notifications: NotificationService | None = None,
    store: ConversationStore | None = None,
    conversation_id: str | None = None,
    request_limit: int | None = None,
    binding: ConversationBinding = DEFAULT_BINDING,
    vision: bool = True,
) -> None:
    # Only the calls still awaiting the operator are announced; the ones a grant or the
    # thread's level already settled ride silently on the parked payload and merge into
    # the resume.
    settled = settled or {}
    pending_names: set[str] = set()
    for call in requests.approvals:
        if call.tool_call_id in settled:
            continue
        pending_names.add(call.tool_name)
        args = call.args_as_dict()
        # A tool may hand the operator a plain-language explanation via an
        # `explanation` argument (the host-execution path requires one); surface
        # it as a distinct field so the client need not parse it out of the args.
        explanation = args.get("explanation")
        run.emit(
            ApprovalRequired(
                tool_call_id=call.tool_call_id,
                name=call.tool_name,
                args=args,
                summary=summarize_call(call.tool_name, args),
                explanation=explanation if isinstance(explanation, str) else None,
            )
        )
    # Fire the ALWAYS-notify policy *before* `run.park(...)` makes the parked status
    # externally visible — not after. This is the one await this function does before
    # parking, and it must land first: `RunRegistry.cancel`'s parked branch assumes
    # "awaiting_input ⇒ the task has already fully exited" and skips the hard-cancel
    # path on that assumption. If the notify (and the conversation-title lookup it may
    # need) instead ran *after* parking, a concurrent cancel/approve landing in that
    # window would see the parked status while this coroutine is still suspended on a
    # real await — violating that assumption and racing the run's own finalize.
    if notifications is not None and pending_names:
        title = await approval_conversation_title(store, run.owner_id, conversation_id)
        try:
            await notifications.notify(
                run.owner_id,
                "approval_needed",
                f'"{title}" needs approval for {", ".join(sorted(pending_names))}',
                conversation_id=conversation_id,
                run_id=run.id,
            )
        except Exception:  # noqa: BLE001 — a notify failure must not break the park
            logger.warning("approval_needed notification failed for run %s", run.id, exc_info=True)
    run.park(
        ParkedTurn(
            agent,
            messages,
            requests,
            announced,
            settled=settled,
            request_limit=request_limit,
            binding=binding,
            vision=vision,
        )
    )
