"""The tool catalog surface — the operator's read + control of which tools the agent gets.

`AE-3.3`: the operator must be able to disable individual tools, and a disabled tool must
not be offered to or invoked by the agent. The enforcement half already exists (the
enabled gate in ``tools/toolsets.py``); this is the half that lets the operator *use* it.

- ``GET /tools`` — every registered tool, namespaced as the agent sees it, with its
  category, its description, and whether it is currently enabled. The catalog comes from
  the live toolset registry (``tools/catalog.py``), so it can never drift from what the
  agent actually runs against.
- ``PUT /tools/{name}`` — flip one tool. An unknown name is a 404 rather than a stored
  setting that disables nothing.

Offline mode's automatic web suspension is deliberately **not** folded into the
``enabled`` flag reported here: this surface reports the operator's own choice, which is
what they can act on. The two sets union at run time (``services/tool_policy``), so a web
tool the operator left enabled is still withheld while offline.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from routes import deps
from services.tool_policy import get_disabled_tools, set_tool_enabled
from tools.catalog import ToolInfo, tool_catalog

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolOut(BaseModel):
    """One row of the catalog."""

    name: str
    category: str
    description: str
    enabled: bool


class ToolUpdate(BaseModel):
    enabled: bool


def _out(info: ToolInfo, disabled: frozenset[str]) -> ToolOut:
    return ToolOut(
        name=info.name,
        category=info.category,
        description=info.description,
        enabled=info.name not in disabled,
    )


@router.get("", response_model=list[ToolOut])
async def list_tools(request: Request) -> list[ToolOut]:
    disabled = await get_disabled_tools(deps.settings_store(request), deps.OPERATOR_ID)
    return [_out(info, disabled) for info in tool_catalog()]


@router.put("/{name}", response_model=ToolOut)
async def update_tool(name: str, body: ToolUpdate, request: Request) -> ToolOut:
    info = next((t for t in tool_catalog() if t.name == name), None)
    if info is None:
        raise HTTPException(status_code=404, detail=f"tool {name!r} not found")
    disabled = await set_tool_enabled(
        deps.settings_store(request), deps.OPERATOR_ID, name, body.enabled
    )
    return _out(info, disabled)
