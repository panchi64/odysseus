"""The mode registry — what kind of work a thread is, answered in one place.

A conversation's mode was a binary asked at half a dozen call sites, each phrasing the
same question its own way: ``mode != "coding"`` in the shell guard, ``mode == "coding"``
in the workspace resolver, ``mode == "coding"`` again in the repo instructions, and two
hand-written frozensets naming the tools each half withheld. Adding a third kind of thread
to that shape means finding every comparison and hoping none was missed — and the ones
that *are* missed fail open, since ``!= "coding"`` reads any unfamiliar mode as a sandbox
thread that may run the code tools.

So the answers move here. One frozen :class:`ModeSpec` per mode carries everything the
rest of the system used to derive by comparison — where the thread's file work happens,
which mode-scoped tool categories it admits, the prompt fragment it adds, the permission
level a new thread in it starts at, and its own floor for the turn's model-round-trip
budget. Call sites ask the registry; a fourth mode becomes a row rather than a hunt.

**Why the tool names are literals.** ``tools/`` sits *above* ``services/`` in the
dependency order, so walking the live catalog here would invert it — the same reason
``services/tool_policy.py`` held these names before. The literal is not left to rot:
``tests/test_modes.py`` pins every category's set against the catalog a real run resolves,
so a renamed, added or dropped tool fails there rather than silently ceasing to be
filtered.

**Why the field is ``mode`` and never ``code_mode``.** ``pydantic_ai_harness`` ships a
capability called ``CodeMode``, and it is an unrelated thing — a context-saving trick
where the model writes one program that calls many tools. This is a mode of the
*conversation*.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from prompts.modes import RESEARCH_MODE

#: The stored vocabulary. ``normal`` and ``code`` were once ``chat`` and ``coding``; the
#: rename is a one-shot migration rather than a compatibility shim, because keeping the
#: old words in the code while the operator's screen says something else is the kind of
#: split that rots.
type ModeId = Literal["normal", "research", "code"]

#: Where a mode's file work happens — the conversation's own container, or a git worktree
#: of a host directory. Matches ``services/workspace.py``'s ``RunWorkspace.kind``, which
#: is the thing this ultimately selects.
type WorkspaceKind = Literal["sandbox", "worktree"]

#: How much rope the model gets. Orthogonal to the mode — every mode carries all four —
#: and enforced elsewhere; a mode only names the one a fresh thread starts at.
type PermissionLevel = Literal["plan", "manual", "edit", "auto"]

#: What an unrecognised stored value resolves to. Normal is the conservative answer: it is
#: the mode that never reaches the host.
DEFAULT_MODE: ModeId = "normal"


#: The tool categories that belong to some modes and not others, with the namespaced names
#: each contributes. A category absent from this mapping is admitted by every mode — the
#: overwhelming majority, and the reason this is a short list rather than a per-mode
#: catalog. Names are ``f"{category}_{tool}"``, which is what the enabled gate matches and
#: what the model is offered.
MODE_SCOPED_TOOLS: Mapping[str, frozenset[str]] = {
    # Code mode's two categories: a shell rooted in the worktree, and the repository's own
    # coding-assistant asset inventory. Registered like every other category and simply
    # withheld from the modes they do not belong to — one catalog, so the operator's
    # settings list and the agent's real stack cannot diverge.
    "shell": frozenset(
        {
            "shell_run_command",
            "shell_start_command",
            "shell_check_command",
            "shell_stop_command",
        }
    ),
    "repo": frozenset({"repo_inventory_agent_context"}),
    # The sandbox runner. Code mode has exactly one way to run something — the shell, in
    # the worktree the file tools are rooted at. Leaving `code_execute` alongside it would
    # offer the model a second filesystem it could edit in and never ship from, which is
    # the failure the one-workspace rule exists to prevent; `code_run_host_command` goes
    # with it because its own sandboxed fence is a different (and, in a worktree,
    # redundant) boundary.
    "code": frozenset({"code_execute", "code_run_host_command"}),
}


@dataclass(frozen=True)
class ModeSpec:
    """One kind of thread, declared rather than derived."""

    #: The stored value, and the identity — ``MODES[spec.id] is spec``.
    id: ModeId
    #: Which workspace a run in this mode resolves (``services/workspace.py``).
    workspace: WorkspaceKind
    #: The **mode-scoped** categories this mode admits, by name. Anything not in
    #: :data:`MODE_SCOPED_TOOLS` is admitted regardless and is deliberately not listed
    #: here — this set answers "which of the contested categories", not "which tools".
    categories: frozenset[str]
    #: The prompt fragment this mode adds, or "" when it adds nothing (:mod:`prompts.modes`
    #: explains why most modes add nothing). Delivered as a dynamic instruction.
    instructions: str = ""
    #: What a fresh thread in this mode starts at. ``edit`` is the level that reproduces
    #: the gate as it stood before permission levels existed: workspace writes pass, and
    #: host, external and outbound effects pause for the operator.
    default_permission: PermissionLevel = "edit"
    #: A floor under the turn's model-round-trip budget, or None to let the operator's
    #: setting decide alone. A mode raises it rather than capping it: the ceiling is the
    #: operator's to set, but a mode that *cannot* do its work inside the default would
    #: otherwise fail at a bound the operator never chose for it.
    request_limit: int | None = None


MODES: Mapping[ModeId, ModeSpec] = {
    "normal": ModeSpec(
        id="normal",
        workspace="sandbox",
        categories=frozenset({"code"}),
    ),
    "research": ModeSpec(
        id="research",
        workspace="sandbox",
        categories=frozenset({"code"}),
        instructions=RESEARCH_MODE,
        # Reading enough sources to see where they disagree is many more round-trips than
        # answering a question, and the operator's chat default is set for the latter.
        request_limit=60,
    ),
    "code": ModeSpec(
        id="code",
        workspace="worktree",
        categories=frozenset({"shell", "repo"}),
    ),
}


def mode_spec(mode: str) -> ModeSpec:
    """The spec for a stored mode value, falling back to Normal.

    Never raises. The values reaching this come off a database row and out of a parked
    run's payload, both of which can outlive a rename; a thread written by an older build
    must keep opening, and it must open as the mode that reaches the least.
    """
    return MODES.get(mode, MODES[DEFAULT_MODE])
