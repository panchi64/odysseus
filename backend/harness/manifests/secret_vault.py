"""The operator's secrets manager (`VAULT-*`) — distinct from the at-rest key
custody vault. Constructing it *is* registering its lock hook (it calls
`vault.register_on_lock` itself), so an app lock ends every secret session too and
there is deliberately nothing more to wire here."""

from __future__ import annotations

from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from routes import secret_vault as secret_vault_routes
from services.secret_vault import SecretVaultService


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    secret_vault = SecretVaultService(ctx.engine, ctx.vault)
    return FeatureRuntime(
        services=(secret_vault,),
        capabilities=(secret_vault,),
        state={"secret_vault": secret_vault},
    )


MANIFEST = FeatureManifest(
    name="secret-vault",
    routers=(secret_vault_routes.router,),
    build=_build,
)
