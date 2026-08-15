"""Email (`EMAIL-1..5`) — accounts, the sync loop, the inbox cache, triage and
drafts. Built right after the attention surface (the other half of their cycle) so
a triage alert has somewhere to land. Its sync worker seals message content, so it
parks while the vault is locked rather than failing. It also stops before the
attention surface (registered after ⇒ stops earlier): the sync loop can raise a
triage alert on its way down, and a channel delivery may still be draining."""

from __future__ import annotations

from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from routes import mail as mail_routes
from services.credential_store import CredentialStore
from services.mail import MailService
from services.notifications import NotificationService
from services.registry import ModelRegistry


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    mail = MailService(
        ctx.engine,
        ctx.vault,
        ctx.services.get(CredentialStore),
        ctx.services.get(ModelRegistry),
        notifications=ctx.services.get(NotificationService),
    )
    await ctx.lifecycle.start("mail", start=mail.start, stop=mail.stop)
    return FeatureRuntime(services=(mail,), capabilities=(mail,), state={"mail": mail})


MANIFEST = FeatureManifest(
    name="mail",
    after=("notifications",),
    routers=(mail_routes.router,),
    build=_build,
)
