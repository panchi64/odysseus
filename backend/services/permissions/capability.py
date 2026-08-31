"""What an action would reach if it ran — its **worst case**, extracted before it runs.

A sensitivity class says what a *tool* can do; this says what *this call* would do. The
difference is the whole reason a level can be reviewed rather than only asked about:
``shell_run_command`` is host execution whatever its arguments say, but `git status` and
`rm -rf ~` are not the same act, and something has to be able to tell them apart without
asking the operator.

**Worst case, never likely case.** Everything here reads an action the way an attacker
would write it. A command is what its syntax permits, not what its author says it does; a
path argument is where it could land, not where it probably lands. That bias is what makes
the extraction usable by a judge that auto-approves: over-describing an action costs a
model call, under-describing one costs the operator something they never agreed to.

**How much can be said varies by tool, and saying so is part of the answer.** A shell
command is read off a grammar (``shell_ast.py``); a file write is one resolved path; an
MCP call is a server, a tool name and a set of argument *keys*, because its effect is
defined on the far side of an API this process cannot see. That last case is not a gap to
be filled in later — it is the honest description, and it is why
:attr:`Capability.unbounded` exists rather than an optimistic empty set.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from services.permissions.shell_ast import ShellCommand, escapes_workspace, shell_reach


class ActionKind(StrEnum):
    """What sort of act this is, which decides what can be said about it at all."""

    #: A command handed to a shell. The only kind the deterministic judge can clear,
    #: because it is the only one whose worst case is readable from a grammar.
    SHELL = "shell"
    #: A named file or directory this installation would change.
    FILE = "file"
    #: A call to something outside — an operator's MCP server, a connector, a mail or
    #: calendar server. The arguments are the far side's vocabulary, not ours.
    EXTERNAL = "external"
    #: Everything else: a tool whose effect is its own and not written in its arguments.
    OPAQUE = "opaque"


@dataclass(frozen=True)
class Capability:
    """The worst case of one deferred call, as facts something else can rule on.

    Deliberately **not** a verdict. This module says what an action reaches; ``judge.py``
    says whether that is allowed and ``reviewer.py`` says whether it was wanted. Keeping
    the three apart is what lets the allowlist change without the extraction changing, and
    what lets a test pin "this command reads these two files" independently of any policy.
    """

    #: The namespaced tool the operator's model asked for.
    tool: str
    kind: ActionKind
    #: One line, in the operator's language: what this would do at its worst. Rides on
    #: the review events and into the reviewer's prompt, so it is the same sentence the
    #: operator reads and the model is judged against — two wordings would be two facts.
    summary: str
    #: Every command a shell action would run, in the order they appear.
    commands: tuple[ShellCommand, ...] = ()
    #: Paths the action names for reading.
    reads: tuple[str, ...] = ()
    #: Paths the action names for writing — a redirect target, a file tool's target.
    writes: tuple[str, ...] = ()
    #: Environment variables the command sets for what it runs.
    env_writes: tuple[str, ...] = ()
    #: Whether the action names something off this machine (a URL, a network redirect).
    network: bool = False
    #: Paths that leave the workspace, or that we cannot place inside it.
    escapes: tuple[str, ...] = ()
    #: Why the worst case could not be pinned down — one entry per construct that was not
    #: interpreted. Non-empty means nothing here may be read as complete.
    unbounded: tuple[str, ...] = field(default_factory=tuple)

    @property
    def bounded(self) -> bool:
        """Whether everything in this action was understood. False ⇒ the fields above
        describe *part* of it, and no caller may treat them as the whole."""
        return not self.unbounded

    @property
    def programs(self) -> tuple[str, ...]:
        """The program names a shell action would run, in order."""
        return tuple(command.program for command in self.commands)


#: Shell-shaped tools, by the argument carrying the command. `code_execute` is here for
#: its `bash` language only — its `python` program is code, not a command line, and there
#: is no grammar walk that bounds an interpreter.
_COMMAND_ARG: dict[str, str] = {
    "shell_run_command": "command",
    "shell_start_command": "command",
    "code_run_host_command": "command",
    "code_execute": "code",
}

#: File tools, by the argument naming the target. Their worst case is one path, which is
#: the whole of what there is to say about them.
_PATH_ARG: dict[str, str] = {
    "files_write_file": "path",
    "files_edit_file": "path",
    "files_create_directory": "path",
}

#: The prefix every operator-supplied MCP and connector tool is named under.
_EXTERNAL_PREFIX = "external_"


def shell_capability(tool: str, command: str, *, root: Path | None) -> Capability:
    """One shell command as a capability — the grammar walk, wrapped in the common shape."""
    reach = shell_reach(command, root=root)
    return Capability(
        tool=tool,
        kind=ActionKind.SHELL,
        summary=f"Runs the shell command: {command}",
        commands=reach.commands,
        reads=reach.reads,
        writes=reach.writes,
        env_writes=reach.env_writes,
        network=reach.network,
        escapes=reach.escapes,
        unbounded=reach.unbounded,
    )


def capability_of(tool: str, args: dict[str, Any], *, root: Path | None = None) -> Capability:
    """The worst case of one deferred call to ``tool`` with ``args``.

    Total: every tool resolves to *something*, because a call that has arrived has to be
    described before it can be ruled on. What varies is how much can be said, and a tool
    this module has no rule for is described by its name and the keys of its arguments —
    enough for a reviewer to judge, and never enough for the judge to clear.
    """
    command_arg = _COMMAND_ARG.get(tool)
    if command_arg is not None:
        return _command_capability(tool, args, command_arg, root)

    path_arg = _PATH_ARG.get(tool)
    if path_arg is not None:
        return _file_capability(tool, args, path_arg, root)

    if tool.startswith(_EXTERNAL_PREFIX):
        # The slug and the far-side tool name, which is all this process knows: an MCP
        # server's arguments are its own vocabulary, and guessing at their meaning would
        # be inventing a boundary rather than describing one.
        source, _, remote = tool.removeprefix(_EXTERNAL_PREFIX).partition("_")
        return Capability(
            tool=tool,
            kind=ActionKind.EXTERNAL,
            summary=(f"Calls {remote or source} on the {source} connector with {_arg_shape(args)}"),
            network=True,
            unbounded=("an external tool's effect is defined on the far side",),
        )

    return Capability(
        tool=tool,
        kind=ActionKind.OPAQUE,
        summary=f"Calls {tool} with {_arg_shape(args)}",
    )


def _command_capability(
    tool: str, args: dict[str, Any], command_arg: str, root: Path | None
) -> Capability:
    command = _text_arg(args, command_arg)
    if command is None:
        return Capability(
            tool=tool,
            kind=ActionKind.SHELL,
            summary=f"Runs {tool} with no command given",
            unbounded=("the call carries no command to read",),
        )
    if tool == "code_execute" and args.get("language", "python") != "bash":
        return Capability(
            tool=tool,
            kind=ActionKind.OPAQUE,
            summary="Runs a program in the conversation's sandbox container",
            network=bool(args.get("network")),
            unbounded=("an interpreter's program is not bounded by its arguments",),
        )
    capability = shell_capability(tool, command, root=root)
    if args.get("network") and not capability.network:
        # The sandbox's egress is off unless this call asked for it, and that ask is an
        # argument of the *tool*, not a word in the command — so the grammar walk cannot
        # see it and the capability would otherwise claim a reach smaller than the real
        # one. Every other field of the walk stands.
        return replace(capability, network=True)
    return capability


def _file_capability(
    tool: str, args: dict[str, Any], path_arg: str, root: Path | None
) -> Capability:
    path = _text_arg(args, path_arg)
    if path is None:
        return Capability(
            tool=tool,
            kind=ActionKind.FILE,
            summary=f"Runs {tool} with no path given",
            unbounded=("the call carries no path to read",),
        )
    return Capability(
        tool=tool,
        kind=ActionKind.FILE,
        summary=f"Writes to {path}",
        writes=(path,),
        escapes=(path,) if escapes_workspace(root, path) else (),
    )


def _text_arg(args: dict[str, Any], name: str) -> str | None:
    value = args.get(name)
    return value if isinstance(value, str) else None


def _arg_shape(args: dict[str, Any]) -> str:
    """An argument set named by its keys, never by its values.

    The shape goes to a model and onto an event; the values may be a password, a mail
    body, or a page of untrusted text. Naming the keys says what kind of call this is
    without moving the payload anywhere it was not already going.
    """
    if not args:
        return "no arguments"
    return "arguments " + ", ".join(sorted(args))
