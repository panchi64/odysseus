"""The `worker` sub-agent — the delegate that *changes* things.

The explorer rides on the harness's `SubAgents`; the worker cannot, and the reason is
structural rather than a preference. That library forwards the parent's `ctx.deps`
verbatim to the child and re-raises `ApprovalRequired` out of it, which is exactly right
for a reader and exactly wrong for a writer: a child sharing its parent's deps writes the
parent's workspace, with no record of who wrote what, and a child that can park the turn
turns one approved delegation into a stream of questions nobody asked for.

So a worker is run here, first-party, and the whole shape follows from three things:

**It works in a fork, never in the parent's workspace.** Its own copy (sandbox) or its own
checkout on its own branch (worktree), taken from what the parent's transcript describes.
What it changed is merged back afterwards and conflicts are *reported*, so a delegated
edit can never silently overwrite work the parent did while it ran (``core/fork.py``).

**Its toolsets are built straight from the categories**, not through
``build_agent_toolsets``. That stack is the *operator's* policy — the permission level's
approval gate, the enabled filter, deferral — and every one of those assumes a
conversation with somebody in it to answer. Marking a child's tools `unapproved` would end
its run with a deferred call nobody will ever settle.

**Nobody is on the other side of it.** The child runs with ``delegated_approved``, which is
what tells the tools that already know about delegation — the shell's approval gate, the
egress request — that this run's work was approved as one act and there is no one to ask.
Anything it could not do comes back in its report, where the parent can act on it.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from pydantic_ai import AbstractToolset, Agent, RunContext

from core.fork import MergeReport
from services.projects.store import ProjectStore
from services.projects.worktree import WorktreeManager
from services.sandbox import SandboxSessionManager
from services.sandbox.shell_runner import FencedShell
from services.workspace import HostFiles, RunWorkspace

from .code import code_toolset
from .delegation import WORKER
from .deps import RunDeps
from .files import files_toolset
from .shell import shell_toolset

logger = logging.getLogger(__name__)

#: How long one worker may run. Long, because a worker that edits and then verifies is
#: doing minutes of real work — but bounded, because the parent's turn is blocked for
#: every second of it and a wedged child would hold it open forever.
_TIMEOUT_S = 900.0

#: How many workers one parent run may set going. Each is a forked workspace and a model
#: loop of its own, so an unbounded delegation is unbounded cost and unbounded blast
#: radius; past this the model is told to do the rest itself, which it always can.
MAX_WORKERS_PER_RUN = 6

#: What a worker is told about the shape it works in. Public because the one thing this
#: brief must not lose — that a worker with a question reports it rather than stalling on
#: it — is the other half of withholding the tools that would ask (`tools/code.py`).
WORKER_BRIEF = (
    "You are a worker agent. You have your own private copy of the workspace: edit it, "
    "run things in it, and check your own work. Nothing you do here touches the "
    "operator's own files, and nothing you do is visible to anyone until you report.\n\n"
    "Do the task you were given and nothing besides it. Every file you change is merged "
    "back into the workspace you were forked from, so an unrelated edit lands there too "
    "— and a file the other agent changed meanwhile comes back as a conflict rather than "
    "as your version winning.\n\n"
    "Verify before you report: run what the task tells you to run, or the project's own "
    "tests. There is nobody to ask here — the conversation belongs to the agent that "
    "delegated to you. If you need something you do not have, a host you cannot reach or "
    "a decision that is not yours, stop and say so in your report; that agent can ask.\n\n"
    "Report what you changed, file by file, what you ran to check it, and — plainly — "
    "whatever you could not finish."
)

_NO_FORK = (
    "The worker could not be given its own copy of the workspace ({reason}), so nothing "
    "was delegated and nothing was changed."
)

_UNAVAILABLE = (
    "Delegation to a worker is unavailable: this conversation has no workspace that can "
    "be forked."
)


@dataclass
class _Fork:
    """A child's workspace and the two things the parent does with it when it is done."""

    workspace: RunWorkspace
    merge: Callable[[], Awaitable[MergeReport]]
    discard: Callable[[], Awaitable[None]]


async def run_worker(
    ctx: RunContext[RunDeps],
    parent: RunWorkspace,
    *,
    task: str,
    background: Any,
    stream: Any,
) -> str:
    """Fork the workspace, run one worker in it, merge what it changed, and report.

    Everything that can fail here degrades to a sentence for the model rather than an
    exception into the parent's turn: a delegation that could not happen is news, not a
    reason to lose the conversation's work.
    """
    deps = ctx.deps
    delegation_id = f"w-{secrets.token_hex(4)}"
    child_key = f"{deps.workspace_key}/{delegation_id}"
    try:
        fork = await _fork(deps, parent, child_key=child_key, delegation_id=delegation_id)
    except Exception as exc:  # noqa: BLE001 — degrade, don't fail the parent's turn
        logger.warning("worker: could not fork %s", deps.workspace_key, exc_info=True)
        return _NO_FORK.format(reason=exc)
    if fork is None:
        return _UNAVAILABLE

    # The parent's memo is dropped and the child's own put in its place: the file and
    # shell tools resolve their root through it, so this is what roots them at the fork
    # rather than at the workspace they were forked from.
    child_deps = replace(deps, workspace_key=child_key, workspace=None, delegated_approved=True)
    child_deps.workspace = fork.workspace
    try:
        report = await _run_child(
            task, child_deps, fork.workspace, background=background, stream=stream
        )
        if report is None:
            # Nothing landed to merge: the worker never reported, so what is in its copy
            # is half-done work nobody has checked. Say so and let the parent decide.
            return (
                "The worker did not finish, so nothing it did was merged back. Nothing "
                "in your workspace changed."
            )
        merged = await fork.merge()
        return f"{report}\n\n{_merge_summary(merged)}"
    except Exception as exc:  # noqa: BLE001 — the report is the hand-back, even when it fails
        logger.warning("worker: delegation in %s failed", child_key, exc_info=True)
        return f"The worker failed and nothing was merged back: {exc}"
    finally:
        # Always, and shielded. A fork is a whole second copy of the workspace — kept
        # around it is disk nobody will ever ask for again, since the id that names it
        # lives only in the call that just ended. An operator pressing Stop unwinds
        # straight through here, and unshielded a second cancellation delivered mid-
        # teardown would leave a container running and a checkout in their repository
        # that nothing ever reaps.
        try:
            await asyncio.shield(fork.discard())
        except Exception:  # noqa: BLE001 — a leftover copy is untidy, never fatal
            logger.warning("worker: could not discard the fork at %s", child_key, exc_info=True)


async def _run_child(
    task: str,
    child_deps: RunDeps,
    workspace: RunWorkspace,
    *,
    background: Any,
    stream: Any,
) -> str | None:
    """The worker's own run, or None when it ran out of time.

    Reasoning is left at the model's own default rather than switched off the way the
    explorer's is: an explorer retrieves, while a worker has to decide what to change and
    whether its change worked.
    """
    shells: list[FencedShell] = []
    agent = Agent[RunDeps, str](
        background.model,
        name=WORKER,
        instructions=WORKER_BRIEF,
        toolsets=child_toolsets(workspace, shells=shells),
    )
    try:
        result = await asyncio.wait_for(
            agent.run(task, deps=child_deps, event_stream_handler=stream), _TIMEOUT_S
        )
    except TimeoutError:
        logger.warning("worker: ran past %ss in %s", _TIMEOUT_S, child_deps.workspace_key)
        return None
    finally:
        # Here rather than beside the discard, because the merge happens in between: a
        # dev server the worker started and never stopped would still be writing into the
        # copy being merged, and then into a checkout about to be removed underneath it.
        # Shielded for the same reason the discard is — the cancellation that skipped
        # `stop_command` must not also skip this.
        await asyncio.shield(_reap(shells))
    return str(result.output)


async def _reap(shells: list[FencedShell]) -> None:
    """Stop what the child left running in the background."""
    for shell in shells:
        try:
            await shell.shutdown()
        except Exception:  # noqa: BLE001 — one stubborn process must not strand the rest
            logger.warning("worker: could not stop a background command", exc_info=True)


def child_toolsets(
    workspace: RunWorkspace, *, shells: list[FencedShell] | None = None
) -> list[AbstractToolset[RunDeps]]:
    """What a worker can do: read and write its copy, and run things in it.

    The categories themselves, unprefixed and ungated — see the module docstring for why
    the app's stack is not what a child is composed with. Both of them rebind to the
    child's own root through the workspace memoised on its deps, which is the same
    mechanism every run uses and not a second way of rooting a toolset.

    ``shells`` is how the shell it gets is handed back for reaping; a sandbox child needs
    no such list, since its processes live in a container the purge removes.
    """
    execution = shell_toolset(shells=shells) if workspace.kind == "worktree" else code_toolset()
    return [files_toolset(), execution]


async def _fork(
    deps: RunDeps, parent: RunWorkspace, *, child_key: str, delegation_id: str
) -> _Fork | None:
    """The child's workspace, forked the way its kind is forked. None when the handles
    that would do it are absent — the same degrade every capability-backed tool makes."""
    if parent.kind == "worktree":
        return await _fork_worktree(deps, delegation_id=delegation_id)
    return await _fork_sandbox(deps, child_key=child_key)


async def _fork_sandbox(deps: RunDeps, *, child_key: str) -> _Fork | None:
    sessions = deps.caps.get_optional(SandboxSessionManager)
    if sessions is None:
        return None
    parent_key = deps.workspace_key
    # The child's run holds it, which is what keeps the live-session cap from displacing a
    # fork mid-delegation — displacing one means deleting it, and nothing here is sealed.
    session = await sessions.fork(parent_key, child_key, holder=deps.run)
    return _Fork(
        workspace=RunWorkspace(root=session.ensure_workspace(), kind="sandbox", files=session),
        merge=lambda: sessions.merge_back(child_key, parent_key),
        discard=lambda: sessions.purge(child_key),
    )


async def _fork_worktree(deps: RunDeps, *, delegation_id: str) -> _Fork | None:
    projects = deps.caps.get_optional(ProjectStore)
    worktrees = deps.caps.get_optional(WorktreeManager)
    if projects is None or worktrees is None or not deps.project_id or not deps.conversation_id:
        return None
    project = await projects.get(deps.owner_id, deps.project_id)
    root = Path(project.root_path)
    where = {
        "project_id": deps.project_id,
        "root": root,
        "conversation_id": deps.conversation_id,
        "delegation_id": delegation_id,
    }
    state = await worktrees.fork(**where)
    return _Fork(
        workspace=RunWorkspace(
            root=state.path,
            kind="worktree",
            files=HostFiles(state.path),
            branch=state.branch,
        ),
        merge=lambda: worktrees.merge_back(**where),
        discard=lambda: worktrees.discard_child(**where),
    )


def _merge_summary(report: MergeReport) -> str:
    """What came back, in the words the parent needs to act on it.

    Conflicts and deletions are named rather than counted: "three files conflicted" is
    not something the agent reading this can do anything with, and the whole point of
    refusing to overwrite is that somebody decides afterwards which version is right.

    What it does *not* say is "compare the two versions". The fork goes away with the
    delegation either way — the id naming it lives only in the call that just ended — so
    the worker's side of a conflict survives as its report and nowhere else, and pointing
    the parent at a copy that is gone costs it a turn discovering that.
    """
    lines = [
        "Merged back into your workspace: "
        + (", ".join(report.files) if report.files else "nothing.")
    ]
    if report.conflicts:
        lines.append(
            "Not merged — you changed these while the worker ran, so your versions "
            "stand: "
            + ", ".join(report.conflicts)
            + ". Its copy is gone with the fork; if you still want its change, make it "
            "yourself from what it reported above."
        )
    if report.deleted:
        # Named on their own line rather than folded into the merged files: "your file
        # changed" and "your file is gone" are not the same sentence, and what a deletion
        # did to the parent differs by workspace kind (`core/fork.py`).
        lines.append("Deleted by the worker: " + ", ".join(report.deleted))
    return "\n".join(lines)
