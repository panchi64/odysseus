"""Every command this request may offer, and what a picked one resolves to.

The registry owns two questions and no others: *which names exist right now*, and *which
spec a typed name means*. What a resolved command then does to the turn is
``expand``'s; what an action does is the client's, over a relay it already has.

**Availability is decided here, never in the picker.** Three things narrow the catalog and
all three are facts only the backend holds: a sub-agent command is pointless where
``subagents_launch`` has been withheld (the operator's own switch, offline mode, the
thread's mode — ``services/tool_policy`` unions them), an action that acts on a
conversation is pointless in a composer that has none, and a mode-scoped command is
pointless outside its mode. A client that filtered any of these would be deciding, and it
would be deciding from a stale copy.

**A collision drops nothing.** Sources are merged by locality — what the installation
ships, then what the operator wrote, then what the project declared — but the loser stays
in the catalog carrying ``shadowed_by``, because a skill and a sub-agent both called
``reviewer`` are two real things and the picker's job is to show the operator that. Only
the *bare* name resolves to one of them; ``/skill:reviewer`` still reaches the other.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from services.skills import SkillStore
from services.subagents import BUILTIN

from .actions import BUILTIN_ACTIONS, NEEDS_CONVERSATION
from .spec import CommandSpec

#: The tool a sub-agent command exists to ask for. Withheld — by the operator's switch, by
#: offline mode, by the thread's mode — and the command is an offer the turn cannot honour.
LAUNCH_TOOL = "subagents_launch"

#: How the picker groups what it is given, in the order the headings appear. The labels
#: live here rather than in the client for the same reason the filtering does: a source
#: added later should show up named, not as a blank heading in a build that has not shipped
#: yet.
GROUPS: tuple[tuple[str, str], ...] = (
    ("action", "This thread"),
    ("skill", "Skills"),
    ("agent", "Sub-agents"),
    ("workflow", "Workflows"),
    ("project", "Project"),
)


@dataclass(frozen=True)
class CatalogEntry:
    """One row of the catalog: a spec, plus what (if anything) outranks its bare name."""

    spec: CommandSpec
    #: The qualified name that wins ``/{spec.name}``, when it is not this one.
    shadowed_by: str | None = None


class CommandRegistry:
    """Assembles the catalog per request. Holds no state of its own."""

    def __init__(self, skills: SkillStore) -> None:
        self._skills = skills

    async def catalog(
        self,
        owner_id: str,
        *,
        mode: str,
        has_conversation: bool,
        disabled_tools: Iterable[str] = (),
    ) -> tuple[CatalogEntry, ...]:
        """What the picker may show, already narrowed and already ranked."""
        withheld = frozenset(disabled_tools)
        specs: list[CommandSpec] = [
            *_actions(has_conversation=has_conversation),
            *await self._skill_specs(owner_id),
            *_agent_specs(withheld=withheld),
        ]
        return _merge([spec for spec in specs if _in_mode(spec, mode)])

    async def resolve(
        self,
        owner_id: str,
        name: str,
        *,
        mode: str,
        has_conversation: bool,
        disabled_tools: Iterable[str] = (),
    ) -> CommandSpec | None:
        """The spec a typed name means, bare or qualified — or ``None``.

        Resolved against the *same* narrowed catalog the picker was served, so a command
        that is not on offer cannot be reached by typing its name anyway. That matters more
        than it looks: the client sends a name, and a name is the one part of this exchange
        the operator can author by hand.
        """
        entries = await self.catalog(
            owner_id,
            mode=mode,
            has_conversation=has_conversation,
            disabled_tools=disabled_tools,
        )
        for entry in entries:
            if entry.spec.qualified_name == name:
                return entry.spec
        for entry in entries:
            if entry.spec.name == name and entry.shadowed_by is None:
                return entry.spec
        return None

    async def _skill_specs(self, owner_id: str) -> list[CommandSpec]:
        """One command per **published** skill.

        ``catalog`` is the published-only view the model already reads, so a draft is no
        more invocable by hand than it is by the model. That keeps publish as the single
        trust boundary rather than adding a second, quieter one here.
        """
        return [
            CommandSpec(
                name=entry.name,
                source="skill",
                kind="prompt",
                title=entry.name,
                description=entry.description,
                target=entry.name,
                argument_hint="what to apply it to",
            )
            for entry in await self._skills.catalog(owner_id)
        ]


def _actions(*, has_conversation: bool) -> list[CommandSpec]:
    """The built-in actions this composer can actually perform."""
    return [
        spec
        for spec in BUILTIN_ACTIONS
        if has_conversation or spec.name not in NEEDS_CONVERSATION
    ]


def _agent_specs(*, withheld: frozenset[str]) -> list[CommandSpec]:
    """One command per sub-agent on the roster.

    Built-ins only, for now. A project's own ``.claude/agents`` declarations need the
    thread's worktree resolved, which is the same root-resolution the file picker needs and
    is built once, with it. Nothing is lost at the moment of use: the command's block names
    the sub-agent *by name*, and ``tools/project_agents.run_roster`` is what resolves that
    name at launch — so a project that shadows ``reviewer`` still gets its own. What is
    missing until then is only that a purely project-declared sub-agent does not appear in
    the picker.
    """
    if LAUNCH_TOOL in withheld:
        return []
    return [
        CommandSpec(
            name=spec.name.replace("_", "-"),
            source="agent",
            kind="prompt",
            title=spec.name.replace("_", " "),
            # Taken verbatim. A roster line is written as a fragment that follows the
            # sub-agent's name ("explorer: searches and reads the workspace…"), which is
            # exactly how the picker stacks a title over a description — so rewriting it
            # here would mean two descriptions of one sub-agent, drifting apart.
            description=spec.description,
            target=spec.name,
            argument_hint="the brief for this sub-agent",
            argument_required=True,
        )
        for spec in BUILTIN
    ]


def _in_mode(spec: CommandSpec, mode: str) -> bool:
    return not spec.modes or mode in spec.modes


def _merge(specs: Sequence[CommandSpec]) -> tuple[CatalogEntry, ...]:
    """Rank the bare-name collisions, keeping every spec.

    Highest tier wins; a tie goes to the one declared first, which within a tier means the
    order the sources are assembled in above. Stable rather than clever: two sources at the
    same tier colliding on a name is already refused where each is created (a unique index,
    a first-wins file scan), so the tiebreak only has to be *decided*, not interesting.
    """
    winners: dict[str, CommandSpec] = {}
    for spec in specs:
        current = winners.get(spec.name)
        if current is None or spec.tier > current.tier:
            winners[spec.name] = spec
    return tuple(
        CatalogEntry(
            spec=spec,
            shadowed_by=(
                None
                if winners[spec.name] is spec
                else winners[spec.name].qualified_name
            ),
        )
        for spec in specs
    )
