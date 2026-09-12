"""Launching a sub-agent, and reading one back — the implementation.

The abstraction lives in ``services/subagents/``, where ``tools/`` can name it; this is the
half that composes an actual chat turn, and so has to sit up here with the wiring. Private
module (the leading underscore keeps manifest discovery from mistaking it for a feature)
beside the manifest that builds it, the same split ``_research_threads.py`` uses and for
the same reason.

Everything here is ordinary, and that is the entire point. There is no sub-agent engine —
no run loop, no step budget of its own, no progress protocol, no second way of holding a
message history. Launching one is: make a conversation, decide how far it may reach and
which files it works on, and submit exactly the turn a route would have submitted. Reading
one is: what did it say, and is it still going. The shortness of this module against what
``tools/worker.py`` used to be is the evidence that nothing was rebuilt.
"""

from __future__ import annotations

import logging
import secrets

from agent.summarize import resolve_auto_compact_policy
from harness.manifest import DormantCategory, HarnessContext
from routes.chat import compose_turn, resolve_turn_models
from runs import RunRegistry, RunStatus
from services.conversations import ConversationBinding, ConversationStore
from services.modes import DEFAULT_MODE, mode_spec
from services.offline import OfflineModeService
from services.permissions import stricter_permission
from services.registry import ModelRegistry
from services.settings_store import (
    SettingsStore,
    get_agent_request_limit_override,
    get_context_thresholds,
)
from services.subagent_store import SubagentStore
from services.subagents.briefing import brief_for
from services.subagents.launcher import (
    LaunchedSubagent,
    SubagentLauncher,
    SubagentParent,
    SubagentUnavailableError,
    SubagentView,
)
from services.subagents.spec import SubagentSpec, WorkspacePolicy
from services.tool_policy import effective_disabled_tools
from services.uploads import UploadStore
from services.workspace import DELEGATION_SEP

logger = logging.getLogger(__name__)

#: The run kind a sub-agent is submitted under. ``linked`` is already defined as "a thread
#: the agent opened for itself" (``runs/lanes.py``) — foreground for the model, background
#: for the operator — which is exactly what this is, so it waits in that lane rather than
#: in one invented here.
SUBAGENT_KIND = "linked"

#: How much of a task is kept as the conversation's name. A sub-agent's thread is hidden
#: from the session list, but the card in the panel is one line wide.
_TITLE_MAX_CHARS = 80

#: How far the isolation asked for at launch may move a spec's own answer. Only one way:
#: a spec that says it works apart cannot be talked into the operator's files, while a
#: spec that shares by default can always be asked to step out of the way.
_ISOLATION_RANK: dict[WorkspacePolicy, int] = {"shared": 0, "isolated": 1, "own": 2}


class ConversationSubagents(SubagentLauncher):
    """Sub-agents, launched and read as ordinary (hidden) conversations.

    Holds handles rather than a request, which is the whole reason it is constructed at
    wiring time: a tool runs deep inside a Run and has no other way to reach turn
    composition.
    """

    def __init__(self, ctx: HarnessContext, records: SubagentStore) -> None:
        self._ctx = ctx
        self._records = records
        self._conversations = ctx.services.get(ConversationStore)
        self._models = ctx.services.get(ModelRegistry)
        self._runs = ctx.services.get(RunRegistry)
        self._settings = ctx.services.get(SettingsStore)
        self._offline = ctx.services.get(OfflineModeService)
        self._uploads = ctx.services.get(UploadStore)

    async def launch(
        self,
        owner_id: str,
        spec: SubagentSpec,
        task: str,
        *,
        parent: SubagentParent | None = None,
        isolate: bool = False,
    ) -> LaunchedSubagent:
        task = task.strip()
        if not task:
            raise SubagentUnavailableError("A sub-agent needs a task to do.")
        parent = parent or SubagentParent()

        try:
            models = await resolve_turn_models(self._models, None, None, owner_id=owner_id)
        except Exception as exc:
            # `resolve_turn_models` answers in HTTP, because its other caller is a route.
            # Down here there is no response to shape — the model asked for a sub-agent and
            # has to be told, in words it can act on, that none can be served.
            raise SubagentUnavailableError(f"No usable model is configured: {exc}") from exc

        mode = spec.mode or parent.mode or DEFAULT_MODE
        # The level the sub-agent runs at, settled before anything is created: what the
        # spec asks for (else the mode's default), capped by what the *parent* was allowed
        # to do. A sub-agent that could act further than the thread that launched it would
        # turn one launch into a standing grant the operator never gave.
        permission = spec.permission_ceiling or mode_spec(mode).default_permission
        if parent.permission is not None:
            permission = stricter_permission(parent.permission, permission)

        binding = ConversationBinding(
            mode=mode, project_id=parent.project_id, permission=permission
        )
        disabled = await effective_disabled_tools(
            self._settings,
            self._offline,
            owner_id,
            mode=binding.mode,
            vision=models[4],
            # Nobody is in the sub-agent's conversation, so it is not offered the tools
            # that would stop and wait for someone.
            kind=SUBAGENT_KIND,
            availability=self._ctx.category_availability,
            caps=self._ctx.capabilities,
        )
        disabled = disabled | spec.withheld | _NO_RECURSION
        # Refuse rather than degrade. A sub-agent missing the one capability its whole
        # job rests on still answers — from the model's own memory — and reads, to
        # everyone downstream, exactly as though it had done the work.
        withheld = spec.required & disabled
        if withheld:
            raise SubagentUnavailableError(
                f"`{spec.name}` needs {', '.join(sorted(withheld))}, which "
                f"{'is' if len(withheld) == 1 else 'are'} switched off or unavailable."
            )

        policy = _isolation(spec.workspace, isolate=isolate)
        delegation_id = f"s-{secrets.token_hex(4)}"
        base = parent.workspace_key or parent.conversation_id or ""
        if not base:
            # Nothing to share. Sharing nothing is not a failure — it just means this
            # sub-agent works in a workspace of its own, which is what every thread with
            # no parent already does. Forking nothing *is* a failure, because there is no
            # copy to take and no merge to make afterwards.
            if policy == "isolated":
                raise SubagentUnavailableError(
                    "This conversation has no workspace to give a sub-agent its own copy "
                    "of. Launch it without isolation, or do the work here."
                )
            policy = "own"
        workspace_key = _workspace_key(base, policy, delegation_id)

        conversation_id = await self._conversations.create_conversation(
            owner_id,
            title=_title_for(spec.name, task),
            project_id=parent.project_id,
            mode=mode,
            permission=permission,
            # Hidden from the session list: nobody can type into a sub-agent, so a thread
            # they cannot use would be noise in the one place they look for their own work.
            # It stays a whole real conversation underneath — readable and streamable by id
            # — which is what the panel opens when a card is expanded.
            ephemeral=True,
        )

        created = compose_turn(
            prompt=task,
            conversation_id=conversation_id,
            models=models,
            # The same assembled capability bag, catalog and instruction set an interactive
            # turn gets, plus this sub-agent's own standing brief. A sub-agent must not
            # quietly be a lesser agent than the one that launched it.
            capabilities=self._ctx.capabilities,
            categories=self._ctx.tool_categories,
            dormant=DormantCategory.summaries(self._ctx.dormant_categories),
            instruction_providers=(
                *self._ctx.instruction_providers,
                _briefing(brief_for(spec.brief, policy)),
            ),
            prompt_context_providers=self._ctx.prompt_context_providers,
            registry=self._runs,
            store=self._conversations,
            uploads=self._uploads,
            disabled_tools=disabled,
            binding=binding,
            # Which files it works on: the launching thread's own workspace, a delegated
            # fork of it, or one of its own (`services/workspace.py` reads the key).
            workspace_key=workspace_key,
            request_limit=spec.request_limit
            or await get_agent_request_limit_override(self._settings, owner_id),
            context_thresholds=await get_context_thresholds(self._settings, owner_id),
            auto_compact=await resolve_auto_compact_policy(self._settings, owner_id),
            owner_id=owner_id,
            kind=SUBAGENT_KIND,
            # A thread nobody is sitting in front of needs a wall clock: the inactivity
            # watchdog cannot end it (a model streaming tokens refreshes that clock on
            # every frame), and a wedged sub-agent would hold its lane for as long as it
            # cared to.
            wall_clock_timeout_s=(
                spec.wall_clock_timeout_s or self._ctx.settings.research_wall_clock_timeout_s
            ),
            # A sub-agent's thread is hidden, so auto-titling it is invisible work that
            # only holds the run open after the answer — it is named from its task above.
            ephemeral=True,
        )

        subagent_id = created.run_id
        await self._records.record(
            subagent_id=subagent_id,
            owner_id=owner_id,
            parent_conversation_id=parent.conversation_id or "",
            child_conversation_id=conversation_id,
            run_id=created.run_id,
            parent_run_id=parent.run_id,
            spec_name=spec.name,
            task=task,
            workspace_policy=policy,
            workspace_key=workspace_key,
            delegation_id=delegation_id if policy == "isolated" else None,
        )
        return LaunchedSubagent(
            subagent_id=subagent_id,
            conversation_id=conversation_id,
            run_id=created.run_id,
            name=spec.name,
            task=task,
        )

    async def read(self, owner_id: str, subagent_id: str) -> SubagentView:
        row = await self._records.get(subagent_id, owner_id)
        if row is None:
            raise SubagentUnavailableError(
                f"No sub-agent {subagent_id!r} — check the id you were given when you "
                "launched it."
            )
        view = self._live_view(row)
        if view.summary is None and view.status in {"running", "blocked"}:
            # Nothing reported yet: hand over its latest answer instead, so a parent
            # checking on a long-running sub-agent sees where it has got to rather than a
            # blank. A current best, explicitly not a report.
            view = _with_summary(view, await self._latest_answer(row.child_conversation_id))
        return view

    async def live(
        self, owner_id: str, *, conversation_id: str | None = None
    ) -> list[SubagentView]:
        rows = await self._records.live(owner_id, parent_conversation_id=conversation_id)
        return [self._live_view(row) for row in rows]

    async def for_parent(self, owner_id: str, conversation_id: str) -> list[SubagentView]:
        """Every sub-agent a thread launched, live and finished — the panel's backfill."""
        rows = await self._records.for_parent(conversation_id, owner_id)
        return [self._live_view(row) for row in rows]

    def _live_view(self, row) -> SubagentView:
        """A stored row, corrected by the Run if one is still going.

        The register is written at the ends of a sub-agent's life; a run in flight knows
        more than it does — whether it has parked on an approval, and how full its context
        has become — so the live numbers win where there are any.
        """
        run = self._runs.get(row.run_id)
        if run is None or run.is_terminal:
            return self._records.view(row)
        metrics = run.metrics
        return self._records.view(
            row,
            status="blocked" if run.status is RunStatus.awaiting_input else "running",
            context_used=getattr(metrics, "context_used", None) if metrics else None,
            context_window=run.context_window,
        )

    async def _latest_answer(self, conversation_id: str) -> str | None:
        turns = await self._conversations.messages_view(conversation_id)
        return next(
            (t.content for t in reversed(turns) if t.role == "assistant" and t.content), None
        )


#: The one tool a sub-agent is never offered. Depth stays 1 by construction rather than by
#: a counter somebody has to remember to increment: a tree of agents is unbounded cost and
#: unbounded blast radius, and nothing about the work needs one.
_NO_RECURSION: frozenset[str] = frozenset({"subagents_launch"})


def _isolation(declared: WorkspacePolicy, *, isolate: bool) -> WorkspacePolicy:
    """Where this launch works, folding the caller's request into the spec's own answer.

    Isolation only ever increases. The launching model knows whether *this* task is one it
    means to work alongside, which the spec cannot; what it does not get to do is pull a
    sub-agent written to stay out of the way back into the operator's own files.
    """
    asked: WorkspacePolicy = "isolated" if isolate else declared
    return asked if _ISOLATION_RANK[asked] > _ISOLATION_RANK[declared] else declared


def _workspace_key(base: str, policy: WorkspacePolicy, delegation_id: str) -> str:
    """The key naming the workspace this sub-agent works in.

    ``own`` is the empty key, which is how every ordinary run says "my own conversation's"
    — the sub-agent's run fills it in for itself, and nothing here has to know how.
    """
    if policy == "own":
        return ""
    if policy == "shared":
        return base
    return f"{base}{DELEGATION_SEP}{delegation_id}"


def _briefing(text: str):
    """This sub-agent's brief as a dynamic instruction.

    An instruction rather than its opening message, because that is the difference between
    a brief and a thing it was told once: instructions are rebuilt every turn and never
    read back out of history, so a file the sub-agent reads later cannot rewrite the terms
    it is working under.
    """

    async def provider(_ctx) -> str:
        return text

    return provider


def _title_for(name: str, task: str) -> str:
    """The sub-agent's thread name — what it is, and what it was asked to do, on one line.

    The task *is* the title, rather than the thread being auto-named from its first
    exchange: nobody wrote this thread's opening message, and a card reading "Untitled" is
    a card the operator cannot tell from the three beside it.
    """
    folded = " ".join(task.split())
    title = f"{name}: {folded}"
    if len(title) <= _TITLE_MAX_CHARS:
        return title
    return title[: _TITLE_MAX_CHARS - 1] + "…"


def _with_summary(view: SubagentView, summary: str | None) -> SubagentView:
    from dataclasses import replace

    return replace(view, summary=summary)
