"""Opening a research thread, and reading one back — the implementation.

The abstraction lives in ``services/research_threads.py``, where ``tools/`` can name it;
this is the half that composes an actual chat turn, and so has to sit up here with the
wiring. It is a private module (the leading underscore is what keeps manifest discovery
from mistaking it for a feature) beside the manifest that builds it, for the same reason
any implementation is split out of a declaration: ``research.py`` should read as *what the
feature is*, not as a hundred lines of how a turn is assembled.

Everything here is ordinary. There is no research machinery left — no rounds loop, no
report store, no progress protocol of its own. Starting research is: make a conversation
in research mode, seed its workspace if the caller handed one over, and submit exactly the
turn a route would have submitted. Reading it is: what did the thread last say, and is it
still working. That is the whole point of the change, and the shortness of this module is
the evidence for it.
"""

from __future__ import annotations

import logging
import shutil
from asyncio import to_thread
from pathlib import Path

from agent.summarize import resolve_auto_compact_policy
from core.exceptions import NotFoundError
from harness.manifest import HarnessContext
from routes.chat import compose_turn, resolve_turn_models
from runs import RunRegistry, RunStatus
from services.conversations import ConversationBinding, ConversationStore
from services.modes import mode_spec
from services.offline import OfflineModeService
from services.permissions import stricter_permission
from services.registry import ModelRegistry
from services.research_threads import (
    ParentThread,
    ResearchThreads,
    ResearchThreadView,
    ResearchUnavailableError,
    StartedResearch,
    title_for,
)
from services.sandbox import SandboxError, SandboxSessionManager
from services.settings_store import (
    SettingsStore,
    get_agent_request_limit_override,
    get_context_thresholds,
)
from services.tool_policy import effective_disabled_tools
from services.uploads import UploadStore
from services.workspace import WORKTREE_SCRATCH

logger = logging.getLogger(__name__)

#: The mode a thread this feature opens is in. Named once so the registry stays the only
#: place that knows what it implies.
RESEARCH_MODE = "research"

#: Research *is* reading the open web. The mode's prompt says gather before you conclude,
#: and these two tools are the only way a thread has to gather; without them the model
#: answers from memory and the thread reads, to the operator, exactly as though it had
#: looked. Named here rather than imported from the web manifest because this states what
#: *research* needs, and the two should not move because the other did.
_REQUIRED_WEB_TOOLS = frozenset({"web_search", "web_fetch"})

#: Never copied into a seeded workspace. `.git` because the copy exists to be *read* — it
#: is analysis, not a checkout, and a repository's history is usually larger than its
#: working tree; the scratch directory because it is our own, in the parent's worktree,
#: and means nothing in a container.
_SEED_EXCLUDES = (".git", WORKTREE_SCRATCH)


class ConversationResearchThreads(ResearchThreads):
    """Research threads, opened and read as ordinary conversations.

    Holds handles rather than a request, which is the whole reason it is constructed at
    wiring time: a tool runs deep inside a Run and has no other way to reach turn
    composition.
    """

    def __init__(self, ctx: HarnessContext) -> None:
        self._ctx = ctx
        self._conversations = ctx.services.get(ConversationStore)
        self._models = ctx.services.get(ModelRegistry)
        self._runs = ctx.services.get(RunRegistry)
        self._settings = ctx.services.get(SettingsStore)
        self._offline = ctx.services.get(OfflineModeService)
        self._uploads = ctx.services.get(UploadStore)
        # Optional by construction: a host with no container runtime has no sandbox at
        # all, which costs a seeded copy and nothing else — the thread still runs.
        self._sandboxes = ctx.services.get_optional(SandboxSessionManager)

    async def start(
        self,
        owner_id: str,
        question: str,
        *,
        context: str = "",
        parent: ParentThread | None = None,
    ) -> StartedResearch:
        question = question.strip()
        if not question:
            raise ResearchUnavailableError("A research thread needs a question.")
        parent = parent or ParentThread()
        try:
            models = await resolve_turn_models(self._models, None, None, owner_id=owner_id)
        except Exception as exc:
            # `resolve_turn_models` answers in HTTP, because its other caller is a route.
            # Down here there is no response to shape — the model asked for research and
            # has to be told, in words it can act on, that the registry cannot serve one.
            raise ResearchUnavailableError(f"No usable model is configured: {exc}") from exc

        # The level the thread will run at, decided before anything is created: the mode's
        # default, capped by whatever the *parent* was allowed to do. A research thread
        # that could act further than the thread that opened it would turn one approved
        # `research_start` into a standing grant the operator never gave.
        permission = mode_spec(RESEARCH_MODE).default_permission
        if parent.permission is not None:
            permission = stricter_permission(parent.permission, permission)

        binding = ConversationBinding(
            mode=RESEARCH_MODE,
            project_id=parent.project_id,
            permission=permission,
        )
        disabled_tools = await effective_disabled_tools(
            self._settings,
            self._offline,
            owner_id,
            mode=binding.mode,
            permission=binding.permission,
            vision=models[4],
            # A thread the agent opened for itself: foreground for the model, background
            # for the operator. Nothing says they are looking at it, so it is not offered
            # the tools that would stop and wait for them.
            kind="linked",
        )
        # Refuse rather than degrade. A thread with no way to reach the web still answers —
        # from the model's own memory — and lands in the operator's session list looking
        # like research. Better to say what is switched off, so the model can fall back to
        # something honest and the operator knows what to turn back on.
        withheld = _REQUIRED_WEB_TOOLS & disabled_tools
        if withheld:
            raise ResearchUnavailableError(
                f"Research needs {', '.join(sorted(withheld))}, which "
                f"{'is' if len(withheld) == 1 else 'are'} switched off or offline."
            )

        conversation_id = await self._conversations.create_conversation(
            owner_id,
            title=title_for(question),
            project_id=parent.project_id,
            mode=RESEARCH_MODE,
            permission=permission,
        )
        if parent.seed_from is not None:
            await self._seed_workspace(conversation_id, parent.seed_from)

        created = compose_turn(
            prompt=_opening_prompt(question, context, seeded=parent.seed_from is not None),
            conversation_id=conversation_id,
            models=models,
            # The same assembled capability bag, catalog and instruction set an
            # interactive turn gets — a thread the agent opened must not quietly be a
            # lesser one than the same thread opened from the composer.
            capabilities=self._ctx.capabilities,
            categories=self._ctx.tool_categories,
            instruction_providers=self._ctx.instruction_providers,
            prompt_context_providers=self._ctx.prompt_context_providers,
            registry=self._runs,
            store=self._conversations,
            uploads=self._uploads,
            disabled_tools=disabled_tools,
            binding=binding,
            # The operator's own ceiling when they set one, exactly as an interactive turn
            # passes it; absent, the engine takes the higher of the config default and the
            # mode's floor — research needs many more round trips than answering a
            # question. Either way the number is not a research-shaped one invented here.
            request_limit=await get_agent_request_limit_override(self._settings, owner_id),
            context_thresholds=await get_context_thresholds(self._settings, owner_id),
            auto_compact=await resolve_auto_compact_policy(self._settings, owner_id),
            owner_id=owner_id,
            # A thread the agent opened for itself: foreground for the model, background
            # for the operator. Its own lane (`runs/lanes.py`) so a handful of them can
            # neither starve the operator's turn nor be starved by the scheduler.
            kind="linked",
            # And a wall clock, which the interactive path leaves to the operator. Nobody
            # is sitting in front of this one: the inactivity watchdog cannot end it (a
            # model streaming tokens refreshes that clock on every frame) and the linked
            # lane is three wide, so three unbounded threads would block every later
            # `research_start` for as long as they cared to run.
            wall_clock_timeout_s=self._ctx.settings.research_wall_clock_timeout_s,
        )
        return StartedResearch(
            conversation_id=conversation_id,
            run_id=created.run_id,
            question=question,
        )

    async def read(self, owner_id: str, conversation_id: str) -> ResearchThreadView:
        summary = await self._conversations.get_summary(conversation_id, owner_id)
        if summary is None:
            raise ResearchUnavailableError(
                f"No conversation {conversation_id!r} — check the id you were given "
                "when the research was started."
            )
        active = self._runs.active_run_for(conversation_id, owner_id)
        turns = await self._conversations.messages_view(conversation_id)
        answer = next(
            (t.content for t in reversed(turns) if t.role == "assistant" and t.content), None
        )
        return ResearchThreadView(
            conversation_id=conversation_id,
            question=summary.title or "",
            status=_status(active.status if active is not None else None, answer),
            answer=answer,
        )

    async def _seed_workspace(self, conversation_id: str, source: Path) -> None:
        """Copy ``source`` into the new thread's sandbox so the research reads a *copy*.

        The alternative is the research thread analysing the very checkout the parent code
        thread is editing — two agents on one working tree, with the operator's diff
        moving underneath the one that is only supposed to be reading.

        Best-effort by design: a thread that starts with an empty workspace still does its
        job (the question and the context carry the substance), while refusing to start
        because a copy failed would lose the research over a convenience.
        """
        if self._sandboxes is None:
            return
        try:
            session = await self._sandboxes.acquire(conversation_id)
            root = session.ensure_workspace()
            await to_thread(
                shutil.copytree,
                source,
                root,
                dirs_exist_ok=True,
                symlinks=True,
                ignore=shutil.ignore_patterns(*_SEED_EXCLUDES),
            )
        except (SandboxError, OSError, NotFoundError):
            logger.warning(
                "research: could not seed %s from %s", conversation_id, source, exc_info=True
            )


def _status(run_status: RunStatus | None, answer: str | None) -> str:
    """The thread's state in one word, from the run that is (or isn't) in flight.

    Deliberately derived rather than stored: the thread has no status column and should
    not grow one — "is it still working" is a fact about the Run registry, and a second
    copy of it would be the thing that goes stale.
    """
    if run_status is not None:
        return "running"
    return "done" if answer else "idle"


def _opening_prompt(question: str, context: str, *, seeded: bool) -> str:
    """The first message of the new thread — the question, plus what the calling thread
    already knows.

    Written as the operator's own opening message rather than as instructions, because
    that is what it is standing in for: the research prompt (`prompts/modes.py`) already
    tells the thread how to work, and repeating that here would only push the part that
    actually varies further from the top.
    """
    parts = [question]
    if context.strip():
        parts.append(f"Context established so far:\n{context.strip()}")
    if seeded:
        parts.append(
            "A copy of the project's working tree has been placed in your workspace — "
            "read it there. It is a copy: nothing you do to it reaches the operator's "
            "own checkout."
        )
    return "\n\n".join(parts)
