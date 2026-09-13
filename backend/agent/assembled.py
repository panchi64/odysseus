"""What a provider will actually be handed, read off a request that is still being assembled.

One function, and it exists because a ``before_model_request`` hook sits at an awkward moment:
the request is complete enough to measure, and one thing about it is not resolved yet.

``ModelRequestParameters.function_tools`` is **every** definition the toolset stack produced,
dormant categories included — the ones whose schemas this installation withholds until the
model asks for the group by name. The library's own ``declared_function_tools`` filters those
out, but it filters them by ``visibility_of``, and ``tool_visibility`` is populated by
``Model.prepare_request``, which runs *inside* the model call — after every capability hook. So
before that, ``visibility_of`` falls back to each definition's own ``defer_loading`` flag,
which **stays set after a reveal** by design (it records what the author asked for, not what
the model can currently see). The consequence for anything reading the request from a hook:

- ``function_tools`` counts withheld schemas that are never sent, and is byte-identical before
  and after a reveal;
- ``declared_function_tools`` drops withheld schemas correctly but *also* drops the ones a
  reveal just brought back, so it is byte-identical before and after a reveal too.

Neither is the wire array, and both are wrong in the same place. ``revealed_tool_names`` is the
missing half and *is* populated by this point — the library derives it from the outgoing
message list before the request — so the two documented fields together give the answer.

**Public API only, and one place for it.** Both readers of an assembled request need the same
answer: the composition readout, which reports what the schemas cost, and the prefix watch,
which reports whether the array moved. Two copies of a rule about a library's resolution order
is one copy that goes stale the day the library changes it.
"""

from __future__ import annotations

from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.tools import ToolDefinition


def declared_function_tools(params: ModelRequestParameters) -> list[ToolDefinition]:
    """The function tools a provider will render in its ``tools`` array, in that order.

    A definition is declared unless it defers its loading and nothing in the history has
    revealed it yet. Output tools are deliberately excluded: they are always rendered, but
    they are not a *category* the operator can switch off and not a schema a reveal moves, so
    the two readers that want them say so themselves.
    """
    revealed = params.revealed_tool_names
    return [
        tool_def
        for tool_def in params.function_tools
        if not tool_def.defer_loading or tool_def.name in revealed
    ]
