"""The command catalog — what the composer's `/` menu may offer right now.

One read, thin over :class:`~services.commands.registry.CommandRegistry`. Everything the
picker appears to decide was decided below this layer: which commands exist, which of them
this thread can actually honour, which one wins a shared name, and what the headings are
called.

**The groups ride the response.** A client that kept its own heading list would show a
blank section the first time a source was added below it, so the labels come down with the
rows. camelCase out, matching ``skills`` beside it.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from routes import deps
from routes.camel import CamelModel
from routes.deps import OPERATOR_ID
from services.commands import GROUPS, CatalogEntry
from services.modes import DEFAULT_MODE, ModeId

router = APIRouter(prefix="/commands", tags=["commands"])


class CommandGroupOut(CamelModel):
    id: str
    label: str
    order: int


class ActionArgumentOut(CamelModel):
    required: bool
    #: A closed set the client may render as a choice, or empty for free text.
    choices: list[str]


class CommandOut(CamelModel):
    name: str
    #: The name that resolves to *this* command and no other (``skill:reviewer``). Always
    #: present, so a client wanting to be unambiguous never has to build one.
    qualified_name: str
    group: str
    title: str
    description: str
    argument_hint: str | None
    kind: str
    #: Set for ``kind == "action"``: the id of a relay the client already owns. One it does
    #: not recognise is a control it should render disabled rather than guess at.
    action_id: str | None
    action_argument: ActionArgumentOut | None
    #: The qualified name that wins this command's bare name, when another source outranks
    #: it. Both rows still ship — the operator gets to see that two things share a name.
    shadowed_by: str | None


class CommandsOut(CamelModel):
    groups: list[CommandGroupOut]
    commands: list[CommandOut]


def _out(entry: CatalogEntry) -> CommandOut:
    spec = entry.spec
    argument = (
        ActionArgumentOut(
            required=spec.argument_required, choices=list(spec.action_choices)
        )
        if spec.kind == "action" and (spec.argument_required or spec.action_choices)
        else None
    )
    return CommandOut(
        name=spec.name,
        qualified_name=spec.qualified_name,
        group=spec.source,
        title=spec.title,
        description=spec.description,
        argument_hint=spec.argument_hint,
        kind=spec.kind,
        action_id=spec.action,
        action_argument=argument,
        shadowed_by=entry.shadowed_by,
    )


@router.get("", response_model=CommandsOut)
async def list_commands(
    request: Request,
    mode: ModeId = DEFAULT_MODE,
    conversation_id: str | None = None,
) -> CommandsOut:
    """The commands offerable in a composer in ``mode``, with or without a thread.

    ``conversation_id`` is presence, not identity: a composer that has not started a thread
    yet cannot compact or fork one, so those rows are simply absent rather than shipped and
    then refused. The thread's own mode is not read from it — the caller passes ``mode``,
    because the launchpad's composer is choosing one rather than reporting one.
    """
    withheld = await deps.disabled_tools(request, mode)
    entries = await deps.commands(request).catalog(
        OPERATOR_ID,
        mode=mode,
        has_conversation=conversation_id is not None,
        disabled_tools=withheld,
    )
    offered = {entry.spec.source for entry in entries}
    return CommandsOut(
        # Only the headings that have something under them: an empty group is a promise
        # the operator has to click to discover is empty.
        groups=[
            CommandGroupOut(id=group, label=label, order=order)
            for order, (group, label) in enumerate(GROUPS)
            if group in offered
        ],
        commands=[_out(entry) for entry in entries],
    )
