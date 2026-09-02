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

**Two kinds of act clear here, and the shorter one first.** A call to a tool this
installation classifies as a *read* (``ActionKind.READ``) is approved outright: the class
is a claim about the tool itself — it returns something and leaves nothing different
behind — so there is no argument set that makes it into another kind of act, and no
reviewer question left to ask. This is what keeps a self-gated recall
(``memory_recall``, ``corpus_retrieve``) from costing a model call every time, and what
stops it from parking a run outright on an installation with no utility model bound. The
class registry is a closed literal pinned against the live catalog by a test, and a name
it has never heard of resolves to the class that reaches *furthest* — so nothing an
operator's own MCP server names can reach this branch.

**Everything else is a shell command, and three rules govern it. None has an exception.**

- An AST shape we do not recognise never passes. It arrives as
  :attr:`Capability.unbounded`, which means the extraction is describing *part* of the
  command — and a part is not something an allowlist can be applied to.
- An environment assignment never passes. `LD_PRELOAD=… ls` is not `ls`, and the set of
  variables that change what a program does is open-ended enough that enumerating the
  dangerous ones is a losing game.
- A variable we cannot interpolate never passes, for the same reason as the first: `$X`
  is whatever it is, and the honest reading of an argument whose value arrives at run time
  is that we did not read it.

**What "read-only" means here, and the assumption underneath it.** The programs on the
list observe and return; the flags that would make one of them do otherwise sit beside it
in ``read_only.py``, so the table states the whole rule rather than half of it. A denial is
matched against the *flag* a token names rather than against the token — `-o`, `-oout.txt`
and `--output=out.txt` are one flag written three ways (``shell_flags.py``). Path arguments
are measured against the run's workspace root and anything reaching outside it escalates.

The assumption worth naming: the shell session persists its working directory between
calls (``tools/shell.py``), and that directory is not visible from here, so a relative
path is judged as relative to the workspace root. Changing directory is therefore
deliberately *not* an allowlisted program — a `cd` is an act the reviewer rules on, with
"moving the working directory outside the workspace" named in its rubric as high risk —
which is what keeps the deterministic stage's base honest.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from services.permissions.capability import ActionKind, Capability
from services.permissions.read_only import READ_ONLY_PROGRAMS, READ_ONLY_SUBCOMMANDS
from services.permissions.shell_ast import ShellCommand
from services.permissions.shell_flags import flag_names, is_flag


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
    """Whether ``capability`` is provably an observation and nothing else.

    Pure and total. Never raises, never calls out, and never returns ``approved`` for
    anything it did not fully understand — the three rules in the module docstring are
    checked before the allowlist is consulted at all, so a command cannot pass on the
    strength of the part of it that parsed.

    ``unbounded`` is tested ahead of every kind check, including the read one, so a
    partially-read action is refused *as* a partially-read action: that is the more
    specific reason, and the reason is what the operator sees on the review row.
    """
    if capability.unbounded:
        return Judgement(False, capability.unbounded[0])
    if capability.kind is ActionKind.READ:
        return Judgement(True, "observes and returns, changing nothing")
    if capability.kind is not ActionKind.SHELL:
        return Judgement(False, "only reads and shell commands can be cleared without a review")
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
    denied = READ_ONLY_PROGRAMS.get(command.program)
    if denied is None:
        return f"runs {command.program}, which is not on the read-only list"
    return _flag_denial(command.program, command.arguments, denied)


def _subcommand_denial(
    command: ShellCommand, subcommands: Mapping[str, frozenset[str]]
) -> str | None:
    """Whether a subcommand-shaped program was invoked in one of its reading forms.

    **Nothing is read past a flag that precedes the subcommand.** Those flags are where the
    act is redirected rather than described — `--git-dir=` and `--work-tree=` move the
    repository, `--exec-path=` moves the binaries git runs, `-c` rewrites the config the
    subcommand obeys, and `-C` moves the directory the whole thing happens in — and a
    reader that skipped them would answer a question about a command that is not the one
    being run. Worse, a global flag taking a *separate* value shifts where the subcommand
    sits, so skipping flags means naming the wrong word as the act. Enumerating git's
    global options here would be a second table to keep in step with git; refusing to read
    past one costs a model call on `git --no-pager log` and cannot be wrong.

    The subcommand is therefore the *first* argument, and it must be one of the reading
    ones, invoked without the flags that would stop it from only reading.
    """
    if not command.arguments:
        return f"runs {command.program} with no subcommand this stage can name"
    subcommand, *rest = command.arguments
    if is_flag(subcommand):
        return (
            f"runs {command.program} with {subcommand} before its subcommand, "
            "which can redirect what the subcommand acts on"
        )
    denied = subcommands.get(subcommand)
    if denied is None:
        return f"runs {command.program} {subcommand}, which is not a read-only subcommand"
    return _flag_denial(f"{command.program} {subcommand}", rest, denied)


def _flag_denial(what: str, arguments: Iterable[str], denied: frozenset[str]) -> str | None:
    """The first denied flag ``arguments`` names, as a refusal — or None when none does.

    Matched against the flags a token *names* rather than against the token, so a rule
    written once as `-o` also covers `-oout.txt` and `--output=out.txt`. Where a token
    reads two ways, every reading counts (``shell_flags.py``): the point of the table is
    that a denied flag cannot be smuggled past it by spelling.
    """
    for argument in arguments:
        used = flag_names(argument) & denied
        if used:
            return f"runs {what} with {sorted(used)[0]}, which does more than read"
    return None
