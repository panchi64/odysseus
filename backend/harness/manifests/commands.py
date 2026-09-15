"""Slash commands — the composer's `/` menu.

Routes only, plus the registry the chat route resolves a picked command through. There is
no toolset and no instruction provider, deliberately: a command is something the *operator*
reaches for, and the model already has every capability behind one. Telling it that a
second way to ask exists would cost every request a paragraph and change nothing about
what it can do.

The registry reads the skill library, so this manifest builds after ``skills``.
"""

from __future__ import annotations

from core.api_scopes import ScopeClaim
from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from routes import commands as command_routes
from services.commands import CommandRegistry
from services.skills import SkillStore


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    registry = CommandRegistry(ctx.services.get(SkillStore))
    return FeatureRuntime(state={"commands": registry})


MANIFEST = FeatureManifest(
    name="commands",
    routers=(command_routes.router,),
    # Filed under `knowledge` beside `/skills`: the catalog is a listing of the operator's
    # own library seen from another angle, and a token allowed one has no reason to be
    # refused the other.
    api_scopes=(ScopeClaim("knowledge", ("/commands",)),),
    after=("skills",),
    build=_build,
)
