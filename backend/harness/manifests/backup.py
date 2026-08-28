"""Encrypted export/import (`BACKUP-*`), under its own operator secret and its own
KDF. What goes in a backup is discovered from the models' own markers — see
`services/backup/manifest.py`."""

from __future__ import annotations

from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from routes import backup as backup_routes
from services.backup import BackupService
from services.settings_store import SettingsStore


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    backup = BackupService(ctx.engine, ctx.vault, ctx.services.get(SettingsStore))
    return FeatureRuntime(services=(backup,), state={"backup": backup})


MANIFEST = FeatureManifest(
    name="backup",
    routers=(backup_routes.router,),
    build=_build,
)
