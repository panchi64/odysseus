"""The calendar (`CAL-1..3`). Nothing to start or stop: no worker, no held
connections — CalDAV sync runs per request. Its natural-language parser resolves
the background model per call, so a role rebound at runtime takes effect without
rebuilding anything."""

from __future__ import annotations

from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from routes import calendar as calendar_routes
from routes.deps import OPERATOR_ID
from services.calendar import CalendarService
from services.calendar.nl import CalendarNaturalLanguage
from services.registry import ModelRegistry


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    registry = ctx.services.get(ModelRegistry)

    async def _resolve_model():
        resolved = await registry.resolve_background(owner_id=OPERATOR_ID)
        return resolved.model, resolved.reasoning_off

    calendar = CalendarService(
        ctx.engine, ctx.vault, nl=CalendarNaturalLanguage(resolve_model=_resolve_model)
    )
    return FeatureRuntime(
        services=(calendar,), capabilities=(calendar,), state={"calendar": calendar}
    )


MANIFEST = FeatureManifest(
    name="calendar",
    routers=(calendar_routes.router,),
    build=_build,
)
