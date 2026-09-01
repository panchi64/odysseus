"""Conversations surface — browse, read, rename, and delete chat threads.

Thin pass-throughs to the :class:`ConversationStore`. Creating a conversation is
a chat concern (``POST /chat`` does it as a side effect of starting a turn); this
router only reads and manages the threads that already exist. History is returned
as a render-ready projection — the durable record stays full-fidelity
``ModelMessage`` blobs; the frontend never sees those.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from agent.summarize import compact_conversation
from agent.title import title_from_history
from core.config import get_settings
from core.exceptions import DegradedCapabilityError, NotFoundError
from routes import deps
from routes.deps import OPERATOR_ID
from runs import ContextWindow, RunMetrics
from services.context_budget import compose
from services.conversation_view import MessageView
from services.conversations import (
    ConversationSummaryView,
    conversation_totals,
    footprint_or_estimate,
    last_request_usage,
)
from services.modes import DEFAULT_MODE, mode_spec
from services.permissions import ACTING_PERMISSIONS, DEFAULT_PERMISSION, PermissionLevel
from services.plans import accepted_plan_prompt, plan_payload
from services.settings_store import (
    get_auto_compact,
    get_context_thresholds,
    resolve_compaction_enabled,
)
from services.workspace_history import SnapshotView, snapshot_id_from_result

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationSummary(BaseModel):
    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int
    preview: str | None = None
    model: str | None = None  # the model the conversation last ran on
    # The live run driving this thread, as its `RunStatus` value (`running`,
    # `queued`, `awaiting_input`); None when nothing is in flight. Derived from the
    # run registry rather than persisted — it lets the thread list mark which
    # conversations are working without opening each one, and keeps the
    # busy-vs-needs-you distinction the nav rail already draws (an `awaiting_input`
    # run is parked on the operator's approval decision, not merely streaming).
    activity: str | None = None
    # What kind of work this thread is. The sidebar shows one mode at a time, so this is
    # on the listing rather than only on the detail — a rail that had to open every
    # thread to know which section it belongs in could not draw itself.
    mode: str = DEFAULT_MODE
    # The **basename** of the directory a code thread works in, and nothing else about
    # it. Null for every other thread, and for a code thread whose project has since been
    # deleted. Deliberately not the path and not the project id: the rail groups code
    # threads under this, it is permanently on screen, and a full path across it would
    # spell out the operator's clients to anyone standing behind them.
    workspace: str | None = None


class ToolCallImageOut(BaseModel):
    """An image the call handed back — base64, scheme added by the renderer. The wire
    twin of the live stream's ``tool.completed`` images, so a screenshot renders in the
    work log identically whether the operator watched it happen or reloaded into it."""

    media_type: str
    data: str


class ToolCallOut(BaseModel):
    id: str
    name: str
    args: dict[str, Any]
    status: str
    result: Any = None
    error: str | None = None
    images: list[ToolCallImageOut] = Field(default_factory=list)


class ViewVersionRefOut(BaseModel):
    """An inline View **chip** re-attached to the message that minted it: a ``show``
    produced a version mid-turn, recoverable from the message's ``view`` tool result
    (which embeds the version id). The chip just labels + opens the version — its bytes
    and files come from the conversation-scoped snapshot the panel reads."""

    snapshot_id: str
    title: str | None
    preview_kind: str | None  # "html" | "image" | "text" | "other" | None — the chip icon


class ViewSnapshotRefOut(BaseModel):
    """A View **version** (workspace snapshot) for the conversation's View, mirroring
    the live ``view.snapshot`` event so a cold read rebuilds the timeline like a warm
    one. Conversation-scoped (it captures the whole workspace), not tied to one
    message; carries how it previews."""

    snapshot_id: str
    title: str | None
    created_at: datetime
    files_changed: int
    summary: str
    preview_kind: str | None
    preview_artifact_id: str | None
    keeper: bool = False  # the operator's durable bookmark on this version


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    reasoning: str | None = None
    tools: list[ToolCallOut] = []
    versions: list[ViewVersionRefOut] = []
    created_at: datetime | None = None
    model: str | None = None  # the model that produced this assistant turn
    # Version navigation: position among this turn's siblings and how many exist.
    # version_count > 1 ⇒ the operator can cycle ‹ k/n › between regenerations/edits.
    version_index: int = 0
    version_count: int = 1
    pinned: bool = False  # the operator's durable bookmark on this turn
    # Upload ids the operator attached to this (user) turn — rendered as file chips.
    attachment_ids: list[str] = []
    # Set when the run behind this assistant turn ended `outcome: "blocked"` (a
    # usage/loop/context/time bound) — the human-readable reason, rendered as a
    # persistent stop marker. None for every other turn.
    blocked_reason: str | None = None
    # `role == "compaction"` only — what the fold cost, so the divider can read
    # "14 messages folded, ~62k → ~4k" with no client-side counting or estimating.
    # The token figures are the same coarse text-only proxy the live
    # `conversation.compacted` event carries (render them as approximate). 0 on every
    # other role.
    messages_compacted: int = 0
    tokens_before: int = 0
    tokens_after: int = 0


class ActiveRun(BaseModel):
    """The in-flight run driving this conversation, when one exists. A streaming
    turn isn't persisted until it finishes, so on a cold read (e.g. a page reload
    mid-stream) the messages alone show no answer — this points the client at the
    run whose events it can replay and resume from ``last_seq``."""

    id: str
    status: str
    last_seq: int


class ConversationDetail(ConversationSummary):
    messages: list[MessageOut]
    # How far the model may go in this thread, so a reload restores the control at the
    # level the operator left it rather than at the default. On the detail and not the
    # listing: it is a fact about the thread you have open, and the sidebar row has no
    # use for it. Always populated — a thread that predates the column reads as the
    # level it was effectively running at.
    permission_level: str = DEFAULT_PERMISSION
    # The View's git-style history — workspace snapshots captured per file-changing
    # turn, newest last. Conversation-scoped; the frontend merges them into the View
    # timeline alongside the per-message versions.
    snapshots: list[ViewSnapshotRefOut] = []
    # The context-window state reconstructed from the last turn's stored usage, so
    # an existing thread shows its fullness on load — not just after the next turn.
    # Null when usage or a window is unavailable.
    context: ContextWindow | None = None
    # The thread's cumulative readout — turns, steps, tokens, cache, wall-clock —
    # rebuilt from the stored messages so the line under the composer says the same
    # thing on a cold load as it did live. Deliberately the **same** `RunMetrics` shape
    # the run stream emits, for the reason `context` above shares `ContextWindow`: one
    # shape from either source means the client has one mapper and the two can't drift.
    # Null for a thread that has never run.
    stats: RunMetrics | None = None
    # Present only while a turn is still streaming server-side — lets a reattaching
    # client resume the live run instead of rendering a reply-less thread.
    active_run: ActiveRun | None = None


class TitleUpdate(BaseModel):
    title: str | None = None


class RetitleRequest(BaseModel):
    """The picker selection to name the thread with. The conversation does not
    persist a per-turn endpoint, so a manual re-title resolves the title model the
    same way a chat turn does — through the operator's current pick — rather than the
    bare default ``main``/``utility`` roles (which a picker-driven operator may never
    have bound). Both optional: an absent pick falls back to those defaults."""

    endpoint_id: str | None = None
    model: str | None = None


class VersionSwitch(BaseModel):
    index: int  # which sibling version to make active (0-based)


class PinUpdate(BaseModel):
    pinned: bool


def _activity(request: Request, conversation_id: str) -> str | None:
    """The status of the live run driving ``conversation_id``, or None when idle.

    Reuses `RunRegistry.active_run_for` so the "which run drives this conversation"
    rule (non-terminal, most recent) lives in exactly one place. Registry-derived,
    not persisted: an in-flight turn isn't written to the store until it finishes,
    so the conversation read alone can't tell a working thread from an idle one.
    """
    run = deps.registry(request).active_run_for(conversation_id, OPERATOR_ID)
    return run.status.value if run is not None else None


def _summary(
    view: ConversationSummaryView,
    activity: str | None = None,
    workspaces: Mapping[str, str] | None = None,
) -> ConversationSummary:
    """One listing row. ``workspaces`` maps project id → directory basename; a caller
    with nothing to look up (a single-thread read, where the group heading is not being
    drawn) passes none and the row simply carries no workspace."""
    return ConversationSummary(
        id=view.id,
        title=view.title,
        created_at=view.created_at,
        updated_at=view.updated_at,
        message_count=view.message_count,
        preview=view.preview,
        model=view.model,
        activity=activity,
        mode=view.mode,
        workspace=(workspaces or {}).get(view.project_id or ""),
    )


def _message_versions(view: MessageView, by_id: dict[str, SnapshotView]) -> list[ViewVersionRefOut]:
    """The View versions this turn minted, recovered from its ``view`` tool results
    (each ``show(file=…)`` embeds the version id). Only a static-preview version folds an
    inline chip — a live/auto version is already marked by its LIVE chip, matching the
    warm stream — so the cold read attaches exactly the chips that warmly streamed."""
    refs: list[ViewVersionRefOut] = []
    for tool in view.tools:
        if not tool.name.endswith("view_show") or not isinstance(tool.result, str):
            continue
        snapshot_id = snapshot_id_from_result(tool.result)
        snapshot = by_id.get(snapshot_id) if snapshot_id else None
        if snapshot is not None and snapshot.preview_kind is not None:
            refs.append(
                ViewVersionRefOut(
                    snapshot_id=snapshot.id,
                    title=snapshot.title,
                    preview_kind=snapshot.preview_kind,
                )
            )
    return refs


def _message(view: MessageView, by_id: dict[str, SnapshotView]) -> MessageOut:
    return MessageOut(
        id=view.id,
        role=view.role,
        content=view.content,
        reasoning=view.reasoning or None,
        tools=[
            ToolCallOut(
                id=t.id,
                name=t.name,
                args=t.args,
                status=t.status,
                result=t.result,
                error=t.error,
                images=[ToolCallImageOut(media_type=i.media_type, data=i.data) for i in t.images],
            )
            for t in view.tools
        ],
        versions=_message_versions(view, by_id),
        created_at=view.timestamp,
        model=view.model,
        version_index=view.version_index,
        version_count=view.version_count,
        pinned=view.pinned,
        attachment_ids=view.attachment_ids,
        blocked_reason=view.blocked_reason,
        messages_compacted=view.messages_compacted,
        tokens_before=view.tokens_before,
        tokens_after=view.tokens_after,
    )


async def _detail(
    request: Request, conversation_id: str, summary: ConversationSummaryView
) -> ConversationDetail:
    """Assemble a conversation's full render-ready detail (active path + the View's
    static versions + reconstructed context-window state). Shared by the read
    endpoint and the navigation endpoints that return the post-move thread (version
    switch, rewind)."""
    store = deps.store(request)
    messages = await store.messages_view(conversation_id)
    # Seed the context meter from the last turn's footprint — or, where the endpoint
    # reported no usage (the common local case), from the same estimate the live gauge
    # falls back to, so reopening a thread doesn't blank a ring that was filling a moment
    # ago. Only pay to resolve the window when there is something to measure against it.
    # The window is the default ``main`` model's (no per-conversation endpoint is
    # persisted, so that's what the next turn would run on).
    history = await store.history(conversation_id)
    overhead = await store.get_overhead(conversation_id)
    used = footprint_or_estimate(
        history,
        overhead,
        fallback_overhead_tokens=get_settings().context_overhead_fallback_tokens,
    )
    window: int | None = None
    context: ContextWindow | None = None
    if used is not None:
        window = await deps.models(request).main_context_window(OPERATOR_ID)
        # The operator's own boundaries, not the defaults: a reloaded thread must show
        # the gauge in the colour the live turn left it, and reading the stored pair here
        # is what keeps a cold load from quietly re-deriving severity against 75/90.
        context = ContextWindow.from_used(
            used,
            window,
            await get_context_thresholds(deps.settings_store(request), OPERATOR_ID),
            # A reload has no request to measure — neither the brief nor the tool schemas
            # reach the message history — so the split leans on what this thread's last
            # turn recorded. Same turn as `used` above, so both halves of the readout
            # describe the same request. Absent for a thread that hasn't run one since
            # this was recorded, which shows as no breakdown rather than a guessed one.
            compose(used, overhead, history),
        )
    # The same figures the live stream reports, rebuilt from the same messages by the
    # same function — the counts and tokens off the active path, the wall-clock off the
    # stored per-response timings (the one thing the messages don't carry). A thread
    # that has never produced a response has nothing to report and sends null, so the
    # readout stays absent rather than rendering a row of zeroes.
    totals = conversation_totals(history)
    stats: RunMetrics | None = None
    if totals.steps:
        timings = await store.timings(conversation_id)
        stats = RunMetrics(
            steps=totals.steps,
            tool_calls=totals.tool_calls,
            turns=totals.turns,
            input_tokens=totals.input_tokens,
            output_tokens=totals.output_tokens,
            cache_read_tokens=totals.cache_read_tokens,
            llm_ms=timings.llm_ms or None,
            tool_ms=timings.tool_ms or None,
            ttft_ms_total=timings.ttft_ms_total or None,
            ttft_samples=timings.ttft_samples,
            context_window=window,
            context_used=used,
            last_request=last_request_usage(history),
        )
    run = deps.registry(request).active_run_for(conversation_id, OPERATOR_ID)
    active_run = (
        ActiveRun(id=run.id, status=run.status.value, last_seq=run.stream.last_seq)
        if run is not None
        else None
    )
    # The conversation's versions, fetched once: the timeline (snapshots[]) and the
    # by-id map the cold-read uses to re-attach each turn's inline chips.
    snapshots = await deps.workspace_history(request).list(OPERATOR_ID, conversation_id)
    by_id = {s.id: s for s in snapshots}
    return ConversationDetail(
        **_summary(
            summary,
            activity=active_run.status if active_run else None,
            workspaces=await deps.projects(request).workspace_names(OPERATOR_ID),
        ).model_dump(),
        messages=[_message(m, by_id) for m in messages],
        snapshots=[
            ViewSnapshotRefOut(
                snapshot_id=s.id,
                title=s.title,
                created_at=s.created_at,
                files_changed=s.files_changed,
                summary=s.summary,
                preview_kind=s.preview_kind,
                preview_artifact_id=s.preview_artifact_id,
                keeper=s.keeper,
            )
            for s in snapshots
        ],
        context=context,
        stats=stats,
        active_run=active_run,
        # Off the thread's own binding, resolved through the registry — so a row written
        # by an older build, or carrying a value this one has no rule for, opens at the
        # level that does the least rather than at whatever the string happens to say.
        permission_level=(await store.binding(conversation_id)).permission,
    )


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(request: Request) -> list[ConversationSummary]:
    views = await deps.store(request).list_conversations(
        OPERATOR_ID, visible_projects=await deps.project_scope(request)
    )
    # Resolved once for the whole listing rather than per row: the rail refreshes on a
    # timer while anything is running, and a decrypt per thread would pay for the same
    # handful of directories over and over.
    workspaces = await deps.projects(request).workspace_names(OPERATOR_ID)
    return [_summary(v, activity=_activity(request, v.id), workspaces=workspaces) for v in views]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, request: Request) -> ConversationDetail:
    summary = await deps.store(request).get_summary(conversation_id, OPERATOR_ID)
    if summary is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return await _detail(request, conversation_id, summary)


@router.patch("/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: str, body: TitleUpdate, request: Request
) -> ConversationSummary:
    store = deps.store(request)
    if await store.get_summary(conversation_id, OPERATOR_ID) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    await store.set_title(conversation_id, body.title)
    summary = await store.get_summary(conversation_id, OPERATOR_ID)
    if summary is None:  # pragma: no cover — just confirmed it exists
        raise HTTPException(status_code=404, detail="conversation not found")
    return _summary(summary, activity=_activity(request, conversation_id))


@router.post("/{conversation_id}/retitle", response_model=ConversationSummary)
async def retitle_conversation(
    conversation_id: str, request: Request, body: RetitleRequest | None = None
) -> ConversationSummary:
    """Regenerate a thread's title on demand, from every question the operator asked
    across the whole conversation — not just its opening line (the first-turn
    auto-titler's input). A manual re-name exists to fix a title that the opening
    missed or that went stale as the thread drifted, so feeding the full arc is what
    makes it meaningful. Only the operator's turns are fed in, never assistant or
    tool output, keeping the small title model off injectable content. Unlike the
    fill-only-if-blank auto-titler, this overwrites unconditionally — it is a
    deliberate operator action.

    The title model is resolved exactly as a chat turn resolves its background work
    (``utility`` → the picked ``main``), requesting reasoning **off** — and it works
    for a picker-driven operator who has no default role bound. The full-arc input here
    is longer than the auto-titler's opening-message excerpt, so a model whose runtime
    ignores the reasoning-off lever (e.g. LM Studio + Qwen) produces a longer ``<think>``
    block; the wider ``retitle_max_tokens`` budget and ``retitle_timeout_s`` give it room
    to think *and* emit the title, which :func:`agent.title` then strips clean."""
    store = deps.store(request)
    if await store.get_summary(conversation_id, OPERATOR_ID) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    pick = body or RetitleRequest()
    try:
        title = await deps.models(request).resolve_background(
            owner_id=OPERATOR_ID,
            override_endpoint_id=pick.endpoint_id,
            override_model=pick.model,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="model endpoint not found") from None
    except DegradedCapabilityError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    name = await title_from_history(
        title.model,
        await store.history(conversation_id),
        full=True,
        reasoning_off=title.reasoning_off,
        timeout_s=get_settings().retitle_timeout_s,
        max_tokens=get_settings().retitle_max_tokens,
    )
    if name is None:
        raise HTTPException(status_code=503, detail="could not generate a title")
    await store.set_title(conversation_id, name)
    summary = await store.get_summary(conversation_id, OPERATOR_ID)
    if summary is None:  # pragma: no cover — just confirmed it exists
        raise HTTPException(status_code=404, detail="conversation not found")
    return _summary(summary, activity=_activity(request, conversation_id))


class OrphanImageAttachments(BaseModel):
    """Image uploads that *this* delete would leave referenced by nothing surviving — the
    set the operator is asked to keep or purge. Empty ⇒ delete straight through (no prompt
    needed). Only images are listed; other attachments (e.g. PDFs) are never auto-purged."""

    upload_ids: list[str]


async def _require_owned(request: Request, conversation_id: str) -> ConversationSummaryView:
    summary = await deps.store(request).get_summary(conversation_id, OPERATOR_ID)
    if summary is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return summary


async def _image_orphans(
    request: Request, conversation_id: str, *, message_id: str | None
) -> list[str]:
    """The image uploads that the proposed delete would orphan — computed before the delete
    runs (the doomed turns must still be in the tree) and filtered to ``image/*``. The store's
    check spares any image still referenced by a surviving branch or another chat."""
    candidates = await deps.store(request).orphaned_attachments_for_delete(
        OPERATOR_ID, conversation_id, message_id=message_id
    )
    return await deps.uploads(request).image_ids(OPERATOR_ID, candidates)


async def _purge_uploads(request: Request, upload_ids: list[str]) -> None:
    """Hard-delete the chosen image uploads (bytes + corpus chunks cascade).
    Best-effort per id, run after the conversation/message is already deleted: one
    already gone (a race) or otherwise failing to delete is logged and skipped, so it never
    aborts the remaining purges or 500s a delete the operator already saw succeed."""
    uploads = deps.uploads(request)
    for upload_id in upload_ids:
        try:
            await uploads.delete(OPERATOR_ID, upload_id)
        except NotFoundError:
            pass
        except Exception:  # noqa: BLE001 — one bad purge mustn't strand the others
            logger.exception("failed to purge orphaned image upload %s", upload_id)


@router.get("/{conversation_id}/orphan-image-attachments", response_model=OrphanImageAttachments)
async def orphan_image_attachments(
    conversation_id: str,
    request: Request,
    message_id: str | None = Query(default=None, alias="messageId"),
) -> OrphanImageAttachments:
    """Pre-delete probe: which image attachments would lose their last reference if this
    message (``message_id``) or the whole conversation (omit it) were deleted. The frontend
    asks this first and only prompts keep-or-delete when the list is non-empty."""
    await _require_owned(request, conversation_id)
    upload_ids = await _image_orphans(request, conversation_id, message_id=message_id)
    return OrphanImageAttachments(upload_ids=upload_ids)


async def _settle_code_branch(request: Request, conversation_id: str, *, discard: bool) -> None:
    """Refuse to delete a code thread that still holds unmerged commits, or throw its
    branch away when the operator said to.

    Best-effort about *everything except the refusal*: a project that has since been
    deleted, or a repository that has moved, leaves nothing to protect and must not block
    the delete. Only a real, countable diff stops it.
    """
    binding = await deps.store(request).binding(conversation_id)
    if mode_spec(binding.mode).workspace != "worktree" or not binding.project_id:
        return
    try:
        project = await deps.projects(request).get(OPERATOR_ID, binding.project_id)
        root = Path(project.root_path)
        diff = await deps.worktrees(request).diff(
            root,
            base_ref=project.base_ref,
            conversation_id=conversation_id,
            project_id=project.id,
        )
    except Exception:  # noqa: BLE001 — no branch, no project, no repo: nothing to lose
        logger.debug("no code branch to settle for %s", conversation_id, exc_info=True)
        return
    if diff.files_changed and not discard:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This code conversation has unmerged work on {diff.branch}: "
                f"{diff.files_changed} file(s), +{diff.insertions} −{diff.deletions}. "
                "Merge it first, or delete with discardBranch=true to throw it away."
            ),
        )
    await deps.worktrees(request).discard(
        root, project_id=binding.project_id, conversation_id=conversation_id
    )


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    request: Request,
    purge_images: bool = Query(default=False, alias="purgeImages"),
    discard_branch: bool = Query(default=False, alias="discardBranch"),
) -> None:
    """Delete a conversation. With ``purgeImages=true`` the operator chose to also delete
    the image attachments this would orphan; the default keeps them.

    A **code** thread with unmerged commits is refused (409) unless
    ``discardBranch=true``. Merging a branch is a deliberate act the operator has to take;
    destroying one must be at least as deliberate, and deleting the thread would otherwise
    be the quiet way to lose work that the merge gate exists to protect.
    """
    store = deps.store(request)
    # The purging delete `routes/deps.claim_conversation` names, and the one mutator here
    # that was not taking the claim. Deleting under a live run tears the tree, the sandbox
    # and the turn's attachments out from beneath it: the run keeps going, its own
    # `_finalize` re-creates a ghost cache entry nothing ever evicts, and the turn is
    # discarded with no error. 409 instead, like every sibling mutation.
    deps.claim_conversation(request, conversation_id)
    try:
        if await store.get_summary(conversation_id, OPERATOR_ID) is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        await _settle_code_branch(request, conversation_id, discard=discard_branch)
        orphans = (
            await _image_orphans(request, conversation_id, message_id=None) if purge_images else []
        )
        await store.delete_conversation(conversation_id)
        await _purge_uploads(request, orphans)
        # Drop the conversation's View history (snapshots + any blob no other snapshot
        # needs), so the work doesn't linger encrypted on disk after the thread is gone.
        await deps.workspace_history(request).delete_for_conversation(OPERATOR_ID, conversation_id)
        # Same reasoning for the agent's task list: it restates what was asked for, so it
        # must not outlive the thread.
        await deps.conversation_plans(request).delete_for_conversation(OPERATOR_ID, conversation_id)
        # Delete the conversation's sandbox too (its workspace + sealed archive),
        # otherwise it lingers on disk keyed to a thread that no longer exists. The DB
        # delete above is the authoritative action, so a purge failure must not fail it.
        sandbox = deps.sandbox_sessions(request)
        if sandbox is not None:
            try:
                await sandbox.purge(conversation_id)
            except Exception:  # noqa: BLE001 — best-effort; the DB delete already succeeded
                logger.warning("sandbox purge failed for %s", conversation_id, exc_info=True)
    finally:
        deps.release_conversation(request, conversation_id)


@router.delete("/{conversation_id}/messages/{message_id}", response_model=ConversationDetail)
async def delete_message(
    conversation_id: str,
    message_id: str,
    request: Request,
    purge_images: bool = Query(default=False, alias="purgeImages"),
) -> ConversationDetail:
    """Remove a turn and everything after it on every branch (its subtree). The
    active path falls back to the deleted turn's parent. With ``purgeImages=true`` the
    image attachments this orphans are deleted too (default keeps them). Returns the
    resulting thread so the client reseats in one round-trip (like version switch / rewind)."""
    store = deps.store(request)
    summary = await _require_owned(request, conversation_id)
    # Claim before the orphan-attachment lookup (real DB awaits, only when
    # purge_images) and the leaf-moving `delete_message` call — a concurrent /chat
    # submission could otherwise land and register its run mid-lookup (nothing has
    # mutated, and no run exists yet, until this call actually deletes), then this
    # delete would proceed to mutate the tree while that new run is live. Released as
    # soon as the tree mutation itself is done — the purge/detail below read but don't
    # move the leaf, so they don't need to stay inside the claim.
    deps.claim_conversation(request, conversation_id)
    try:
        orphans = (
            await _image_orphans(request, conversation_id, message_id=message_id)
            if purge_images
            else []
        )
        if not await store.delete_message(conversation_id, message_id):
            raise HTTPException(status_code=404, detail="message not found")
    finally:
        deps.release_conversation(request, conversation_id)
    await _purge_uploads(request, orphans)
    return await _detail(request, conversation_id, summary)


@router.post("/{conversation_id}/messages/{message_id}/version", response_model=ConversationDetail)
async def switch_version(
    conversation_id: str, message_id: str, body: VersionSwitch, request: Request
) -> ConversationDetail:
    """Cycle a turn to one of its sibling versions (a prior regeneration/edit) and
    return the resulting thread."""
    store = deps.store(request)
    summary = await _require_owned(request, conversation_id)
    # Moves the active leaf — must not race an in-flight turn built from the leaf
    # this would move away from (or another in-flight claim on this conversation).
    deps.claim_conversation(request, conversation_id)
    try:
        if not await store.switch_version(conversation_id, message_id, body.index):
            raise HTTPException(status_code=404, detail="version not found")
    finally:
        deps.release_conversation(request, conversation_id)
    return await _detail(request, conversation_id, summary)


@router.post("/{conversation_id}/messages/{message_id}/pin", status_code=204)
async def pin_message(
    conversation_id: str, message_id: str, body: PinUpdate, request: Request
) -> None:
    """Pin or unpin a turn — a durable bookmark surfaced in the projection."""
    store = deps.store(request)
    await _require_owned(request, conversation_id)
    # A tree mutation like the others here — rejected while a run is live on this
    # conversation, same as switch_version/rewind/delete_message.
    deps.claim_conversation(request, conversation_id)
    try:
        if not await store.set_pin(conversation_id, message_id, body.pinned):
            raise HTTPException(status_code=404, detail="message not found")
    finally:
        deps.release_conversation(request, conversation_id)


@router.post("/{conversation_id}/messages/{message_id}/rewind", response_model=ConversationDetail)
async def rewind(conversation_id: str, message_id: str, request: Request) -> ConversationDetail:
    """Move the active tip back to this turn so the thread ends there; the next
    message branches from it (the later turns stay reachable as a sibling version)."""
    store = deps.store(request)
    summary = await _require_owned(request, conversation_id)
    # Moves the active leaf — see switch_version's guard note above.
    deps.claim_conversation(request, conversation_id)
    try:
        if not await store.rewind(conversation_id, message_id):
            raise HTTPException(status_code=404, detail="message not found")
    finally:
        deps.release_conversation(request, conversation_id)
    return await _detail(request, conversation_id, summary)


@router.post("/{conversation_id}/messages/{message_id}/fork", response_model=ConversationDetail)
async def fork(conversation_id: str, message_id: str, request: Request) -> ConversationDetail:
    """Start a **new** conversation carrying this thread's history up to this turn.

    Unlike rewind/regenerate/edit — which move the active tip inside one thread's tree —
    this leaves the source thread untouched and returns the *new* conversation, so the
    client navigates to it in one round-trip.

    The source is claimed for the duration of the walk: a run appending to it mid-copy
    would produce a fork of a history that never existed.
    """
    await _require_owned(request, conversation_id)
    store = deps.store(request)
    deps.claim_conversation(request, conversation_id)
    try:
        forked_id = await store.fork(conversation_id, message_id, OPERATOR_ID)
    finally:
        deps.release_conversation(request, conversation_id)
    if forked_id is None:
        raise HTTPException(status_code=404, detail="message not found")
    await _branch_the_fork(request, conversation_id, forked_id)
    summary = await store.get_summary(forked_id, OPERATOR_ID)
    if summary is None:  # pragma: no cover — just created above
        raise HTTPException(status_code=404, detail="conversation not found")
    return await _detail(request, forked_id, summary)


async def _branch_the_fork(request: Request, source_id: str, forked_id: str) -> None:
    """Give a forked **code** thread a branch cut from the source's, not from the
    project's base ref.

    The copied transcript describes files as they are on the source conversation's branch.
    Branching the fork from `base_ref` — what a first code turn would otherwise do —
    would hand it a tree that does not match the history it was given, which is precisely
    what forking is supposed to preserve. Best-effort: a source that never cut a branch
    leaves the fork to create one normally on its first code turn.
    """
    binding = await deps.store(request).binding(forked_id)
    if mode_spec(binding.mode).workspace != "worktree" or not binding.project_id:
        return
    try:
        project = await deps.projects(request).get(OPERATOR_ID, binding.project_id)
        await deps.worktrees(request).branch_from(
            Path(project.root_path), source_id=source_id, conversation_id=forked_id
        )
    except Exception:  # noqa: BLE001 — no source branch yet; the fork cuts its own later
        logger.debug("fork %s: no source branch to base on", forked_id, exc_info=True)


class ApprovalGrantOut(BaseModel):
    """A live conversation-scoped tool auto-approval grant, for the operator's
    visible + revocable list."""

    tool_name: str
    expires_at: datetime


@router.get("/{conversation_id}/grants", response_model=list[ApprovalGrantOut])
async def list_grants(conversation_id: str, request: Request) -> list[ApprovalGrantOut]:
    """The tools the operator allowed to auto-approve for the rest of this conversation."""
    await _require_owned(request, conversation_id)
    grants = await deps.approval_grants(request).list(OPERATOR_ID, conversation_id)
    return [ApprovalGrantOut(tool_name=g.tool_name, expires_at=g.expires_at) for g in grants]


class PlanItemOut(BaseModel):
    id: str
    content: str
    status: str
    active_form: str | None = None


@router.get("/{conversation_id}/plan", response_model=list[PlanItemOut])
async def read_plan(conversation_id: str, request: Request) -> list[PlanItemOut]:
    """The agent's current task list for this thread.

    The list is streamed as it changes (``plan.updated``), but a client that opens or
    reloads a conversation has no stream to replay — this is how it starts from the
    truth rather than from an empty panel that only fills on the next mutation.
    """
    await _require_owned(request, conversation_id)
    items = await deps.conversation_plans(request).items(OPERATOR_ID, conversation_id)
    return [PlanItemOut(**row) for row in plan_payload(items)]


class PlanAccept(BaseModel):
    """Which level to raise the thread to. Only one that can act: accepting a plan and
    staying read-only is a no-op with extra steps, and dropping to Manual is a downgrade
    the composer's own control already offers.

    *Which* levels those are is the permission registry's answer, not a pair spelled out
    here — a fifth preset is a row in ``services/permissions/levels.py`` and nothing in
    this route moves."""

    level: PermissionLevel = DEFAULT_PERMISSION

    @field_validator("level")
    @classmethod
    def _must_be_able_to_act(cls, value: PermissionLevel) -> PermissionLevel:
        if value not in ACTING_PERMISSIONS:
            raise ValueError(
                f"level must be one of {', '.join(sorted(ACTING_PERMISSIONS))} — "
                "the levels a thread can act at"
            )
        return value


class PlanAccepted(BaseModel):
    """What the thread is now, and the message that starts the turn which acts on it.

    The prompt is handed back rather than sent, because sending is a turn: it goes
    through ``POST /chat`` like every other message, with that route's claim, its bounds
    and its place in the transcript. Accepting only clears the way."""

    permission_level: str
    prompt: str


@router.post("/{conversation_id}/plan/accept", response_model=PlanAccepted)
async def accept_plan(
    conversation_id: str, request: Request, body: PlanAccept | None = None
) -> PlanAccepted:
    """Accept the plan this thread produced and let it act.

    The closing half of the Plan level's contract. A Plan turn is offered no tool that
    changes anything, so the only way it can end is by writing down what it would do; this
    is the operator reading that and saying yes. It raises the thread's level — nothing
    else about the thread moves — and returns the plan as the message to send next.

    ``409`` when there is no plan to accept: a thread with an empty task list has produced
    nothing to agree to, and raising the level on the strength of it would be granting on
    the basis of a document that does not exist. (A locked vault also reads as no plan;
    the level stays where it is, which is the right way for that to fail.)
    """
    await _require_owned(request, conversation_id)
    items = await deps.conversation_plans(request).items(OPERATOR_ID, conversation_id)
    if not items:
        raise HTTPException(status_code=409, detail="there is no plan to accept")
    level = (body or PlanAccept()).level
    stored = await deps.store(request).set_permission_level(conversation_id, level)
    return PlanAccepted(permission_level=stored, prompt=accepted_plan_prompt(items))


@router.delete("/{conversation_id}/grants/{tool_name}", status_code=204)
async def revoke_grant(conversation_id: str, tool_name: str, request: Request) -> None:
    """Revoke a conversation auto-approval — the next call to that tool asks again."""
    await _require_owned(request, conversation_id)
    await deps.approval_grants(request).revoke(OPERATOR_ID, conversation_id, tool_name)


class CompactionOverrideUpdate(BaseModel):
    """Set a conversation's compaction override: ``null`` inherits the operator's global
    setting; ``true``/``false`` forces compaction on/off for this thread."""

    override: bool | None = None


class CompactionOverrideOut(BaseModel):
    """The thread's compaction state: the stored ``override`` (``null`` = inherit) plus the
    ``effective`` on/off after resolving it against the operator's global setting — so the UI
    renders the real state without re-deriving it."""

    override: bool | None
    effective: bool


async def _compaction_state(request: Request, conversation_id: str) -> CompactionOverrideOut:
    """This thread's auto-compaction state: the stored override plus the effective on/off
    after resolving it against the operator's global default."""
    override = await deps.store(request).get_compaction_override(conversation_id)
    global_cfg = await get_auto_compact(deps.settings_store(request), OPERATOR_ID)
    return CompactionOverrideOut(
        override=override,
        effective=resolve_compaction_enabled(override, global_cfg.enabled),
    )


@router.get("/{conversation_id}/auto-compact", response_model=CompactionOverrideOut)
async def get_auto_compact_override(
    conversation_id: str, request: Request
) -> CompactionOverrideOut:
    """This thread's conversation-compaction state (its override + the effective on/off) —
    whether its older turns fold into a summary once the context window fills."""
    await _require_owned(request, conversation_id)
    return await _compaction_state(request, conversation_id)


@router.put("/{conversation_id}/auto-compact", response_model=CompactionOverrideOut)
async def set_auto_compact_override(
    conversation_id: str, body: CompactionOverrideUpdate, request: Request
) -> CompactionOverrideOut:
    """Force conversation compaction on/off for this thread, or clear it (``null``) to
    inherit the operator's global setting."""
    await _require_owned(request, conversation_id)
    await deps.store(request).set_compaction_override(conversation_id, body.override)
    return await _compaction_state(request, conversation_id)


@router.post("/{conversation_id}/compact", response_model=ConversationDetail)
async def compact_conversation_now(
    conversation_id: str, request: Request, body: RetitleRequest | None = None
) -> ConversationDetail:
    """Fold this thread's older turns into a summary now, without waiting for it to reach
    the automatic threshold — for a thread the operator knows is about to need the room.

    Unlike the automatic path this ignores the threshold and the on/off switches entirely:
    the operator asked for it explicitly. It still respects everything that makes a
    compaction *safe* — the retained tail, the never-reach-past-an-earlier-checkpoint rule,
    and the refusal to graft onto a branch point.

    Claims the conversation for the duration, which ``retitle`` (whose shape this otherwise
    follows) does not need to: this one appends to the tree, so it must not run beside a
    live turn recording its own messages. Returns the refreshed detail so the client renders
    the new divider from the same shape a cold read gives it.

    ``503`` when the summarizer couldn't produce a summary; ``409`` when nothing was folded
    — either the thread is too short to have anything to fold, or the operator has just
    started a regenerate/edit and the leaf is a branch point."""
    store = deps.store(request)
    summary = await store.get_summary(conversation_id, OPERATOR_ID)
    if summary is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    pick = body or RetitleRequest()
    deps.claim_conversation(request, conversation_id)
    try:
        try:
            utility = await deps.models(request).resolve_background(
                owner_id=OPERATOR_ID,
                override_endpoint_id=pick.endpoint_id,
                override_model=pick.model,
            )
        except NotFoundError:
            raise HTTPException(status_code=404, detail="model endpoint not found") from None
        except DegradedCapabilityError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        # The threshold and the on/off switch are deliberately ignored here, but the
        # retained tail is not: it is how much of the work in flight survives the fold, and
        # the operator's answer to that is the same whether the fold was asked for or fired
        # on its own.
        auto = await get_auto_compact(deps.settings_store(request), OPERATOR_ID)
        outcome = await compact_conversation(
            store,
            conversation_id,
            model=utility.model,
            reasoning_off=utility.reasoning_off,
            keep_turns=auto.keep_turns,
        )
        if outcome is None:
            raise HTTPException(
                status_code=409, detail="there is nothing to compact in this conversation"
            )
    finally:
        deps.release_conversation(request, conversation_id)
    refreshed = await store.get_summary(conversation_id, OPERATOR_ID)
    if refreshed is None:  # pragma: no cover — just confirmed it exists
        raise HTTPException(status_code=404, detail="conversation not found")
    return await _detail(request, conversation_id, refreshed)
