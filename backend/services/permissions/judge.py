"""The deterministic stage — the answer that costs nothing.

Most of what an agent does at the Auto level is looking: `git status`, `ls src`,
`grep -rn foo .`, `wc -l`. Sending each of those to a model costs a round trip, a second
of latency and a chance of being wrong about something a grammar already settles. So the
first stage is a **strict allowlist over an extracted capability** (``capability.py``),
and only what it declines reaches the reviewer.

**It has exactly one power: to approve.** A capability this stage does not recognise is
not refused — it is *escalated*, which is a different thing and the reason the allowlist
can afford to be as narrow as it is. Narrowing it costs model calls; widening it costs the
operator's trust, and only one of those is recoverable.

**Three rules, and none of them has an exception.**

- An AST shape we do not recognise never passes. It arrives as
  :attr:`Capability.unbounded`, which means the extraction is describing *part* of the
  command — and a part is not something an allowlist can be applied to.
- An environment assignment never passes. `LD_PRELOAD=… ls` is not `ls`, and the set of
  variables that change what a program does is open-ended enough that enumerating the
  dangerous ones is a losing game.
- A variable we cannot interpolate never passes, for the same reason as the first: `$X`
  is whatever it is, and the honest reading of an argument whose value arrives at run time
  is that we did not read it.

**What "read-only" means here, and the assumption underneath it.** Every allowlisted
program observes and returns; none of them writes, and the few that *could* under a flag
carry that flag as a denial beside them, so the table states the whole rule rather than
half of it. Path arguments are measured against the run's workspace root and anything
reaching outside it escalates.

The assumption worth naming: the shell session persists its working directory between
calls (``tools/shell.py``), and that directory is not visible from here, so a relative
path is judged as relative to the workspace root. Changing directory is therefore
deliberately *not* an allowlisted program — a `cd` is an act the reviewer rules on, with
"moving the working directory outside the workspace" named in its rubric as high risk —
which is what keeps the deterministic stage's base honest.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from services.permissions.capability import ActionKind, Capability
from services.permissions.shell_ast import ShellCommand

#: Programs that only ever observe, each with the flags that would make it do otherwise.
#: An empty set means the program cannot write however it is invoked.
#:
#: Grouped as one table because the exceptions are the interesting part: `find` is on the
#: list *because* its writing forms are enumerable, and a reader can check that claim in
#: one place. A program whose writing forms are not enumerable — `sed -i` hides behind a
#: short-flag cluster, `awk` writes from inside its own program text, `xargs` runs someone
#: else's — is simply absent, and escalates.
READ_ONLY_PROGRAMS: Mapping[str, frozenset[str]] = {
    "basename": frozenset(),
    "cat": frozenset(),
    "cksum": frozenset(),
    "cmp": frozenset(),
    "column": frozenset(),
    "comm": frozenset(),
    "cut": frozenset(),
    "date": frozenset(),
    "df": frozenset(),
    "diff": frozenset(),
    "dirname": frozenset(),
    "du": frozenset(),
    "echo": frozenset(),
    "false": frozenset(),
    "file": frozenset(),
    # Everything `find` does beyond listing is one of these predicates, and they are exact
    # tokens rather than clustered short flags, so the denial is complete.
    "find": frozenset(
        {
            "-delete",
            "-exec",
            "-execdir",
            "-ok",
            "-okdir",
            "-fls",
            "-fprint",
            "-fprint0",
            "-fprintf",
        }
    ),
    "grep": frozenset(),
    "head": frozenset(),
    "hostname": frozenset(),
    "id": frozenset(),
    "jq": frozenset(),
    "ls": frozenset(),
    "md5sum": frozenset(),
    "nl": frozenset(),
    "printf": frozenset(),
    "pwd": frozenset(),
    "readlink": frozenset(),
    "realpath": frozenset(),
    "rg": frozenset(),
    "sha1sum": frozenset(),
    "sha256sum": frozenset(),
    "shasum": frozenset(),
    "sort": frozenset(),
    "stat": frozenset(),
    "tail": frozenset(),
    "tr": frozenset(),
    "true": frozenset(),
    "uname": frozenset(),
    "uniq": frozenset(),
    "wc": frozenset(),
    "which": frozenset(),
    "whoami": frozenset(),
}

#: Programs where the *subcommand* is the act. `git` is the one that matters: it is the
#: most-run program in a code thread and most of what it does is read, but the same binary
#: also commits, pushes and resets. The program is allowlisted only for these first words.
READ_ONLY_SUBCOMMANDS: Mapping[str, frozenset[str]] = {
    "git": frozenset(
        {
            "blame",
            "cat-file",
            "describe",
            "diff",
            "grep",
            "log",
            "ls-files",
            "ls-tree",
            "rev-parse",
            "shortlog",
            "show",
            "status",
        }
    ),
}


@dataclass(frozen=True)
class Judgement:
    """The deterministic stage's answer about one capability.

    ``approved`` is the only field a caller branches on. ``reason`` exists for the other
    half of the job — an operator watching a benign-looking command escalate needs to be
    told *which* part of it this stage would not vouch for, or the escalation reads as
    the system being arbitrary.
    """

    approved: bool
    reason: str


def judge(capability: Capability) -> Judgement:
    """Whether ``capability`` is provably a read of the workspace and nothing else.

    Pure and total. Never raises, never calls out, and never returns ``approved`` for
    anything it did not fully understand — the three rules in the module docstring are
    checked before the allowlist is consulted at all, so a command cannot pass on the
    strength of the part of it that parsed.
    """
    if capability.kind is not ActionKind.SHELL:
        return Judgement(False, "only shell commands can be cleared without a review")
    if capability.unbounded:
        return Judgement(False, capability.unbounded[0])
    if capability.env_writes:
        names = ", ".join(capability.env_writes)
        return Judgement(False, f"sets {names} for the command it runs")
    if capability.writes:
        return Judgement(False, f"writes to {capability.writes[0]}")
    if capability.network:
        return Judgement(False, "reaches the network")
    if capability.escapes:
        return Judgement(False, f"names {capability.escapes[0]}, outside the workspace")
    if not capability.commands:
        return Judgement(False, "runs no command this stage can name")
    for command in capability.commands:
        denial = _denial(command)
        if denial is not None:
            return Judgement(False, denial)
    return Judgement(True, "reads the workspace and changes nothing")


def _denial(command: ShellCommand) -> str | None:
    """Why ``command`` is not clearable, or None when it is.

    A program is looked up by its bare name — a path-qualified invocation (`/bin/ls`,
    `./ls`) is deliberately *not* the same thing, because the name no longer says which
    binary runs, and the containment check has already had its say about the path.
    """
    subcommands = READ_ONLY_SUBCOMMANDS.get(command.program)
    if subcommands is not None:
        return _subcommand_denial(command, subcommands)
    writing_flags = READ_ONLY_PROGRAMS.get(command.program)
    if writing_flags is None:
        return f"runs {command.program}, which is not on the read-only list"
    used = writing_flags.intersection(command.arguments)
    if used:
        return f"runs {command.program} with {sorted(used)[0]}, which writes"
    return None


def _subcommand_denial(command: ShellCommand, subcommands: frozenset[str]) -> str | None:
    """Whether a subcommand-shaped program was invoked in one of its reading forms.

    The subcommand is the first argument that is not a flag — `git -C src status` is
    `status`, and `git --version` is no subcommand at all and escalates. Global flags that
    take a value would shift that position, which is precisely why a program lands in this
    table only when its reading subcommands are worth enumerating one by one.
    """
    for argument in command.arguments:
        if argument.startswith("-"):
            continue
        if argument in subcommands:
            return None
        return f"runs {command.program} {argument}, which is not a read-only subcommand"
    return f"runs {command.program} with no subcommand this stage can name"
