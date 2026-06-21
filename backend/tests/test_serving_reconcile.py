"""reconcile_on_startup — a restart clean-slates mid-flight managed models.

A served engine's process handle doesn't survive a backend restart, so on startup the
service can't adopt it: it best-effort terminates the recorded pid, marks the row
``stopped``, and disables the endpoint (resolve then skips the dead port while the role
binding survives). Re-serving allocates a fresh port.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from core.db import init_db, make_engine
from core.vault import Vault
from services.cookbook import CookbookService
from services.registry import ModelRegistry
from services.serving import (
    EngineKind,
    ServeState,
    ServingPaths,
    ServingService,
    Workload,
)
from services.serving.adapters.fake import FakeAdapter
from services.serving.supervisor import ProcessSupervisor

OWNER = "operator"


async def _service(tmp_path: Path) -> tuple[ServingService, ModelRegistry]:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("test-passphrase")
    registry = ModelRegistry(engine, vault)
    service = ServingService(
        engine,
        vault,
        registry,
        CookbookService(),
        ServingPaths(tmp_path),
        adapters={EngineKind.llama_cpp: FakeAdapter()},
        supervisor=ProcessSupervisor(),
    )
    return service, registry


async def test_reconcile_clean_slates_running_rows_and_kills_orphans(tmp_path: Path):
    service, registry = await _service(tmp_path)
    # A leftover endpoint from the "prior process": enabled and role-bound.
    endpoint = await registry.create_endpoint(
        OWNER,
        name="Local · acme/m",
        base_url="http://127.0.0.1:9/v1",
        model="acme/m",
        native_tools=True,
    )
    await registry.set_role(OWNER, "main", [endpoint.id])
    # An orphan engine process that "outlived" the prior backend.
    orphan = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(30)"
    )
    # Seed a managed row as if it were running before the restart.
    row = await service._store.get_or_create(
        OWNER, EngineKind.llama_cpp, "acme/m", Workload.chat, None
    )
    await service._store.update(
        row.id,
        state=ServeState.running,
        pid=orphan.pid,
        port=54321,
        endpoint_id=endpoint.id,
    )

    await service.reconcile_on_startup()

    # The row is clean-slated (stopped, port + pid cleared) …
    reconciled = await service._store.get(row.id)
    assert reconciled is not None
    assert reconciled.state == ServeState.stopped.value
    assert reconciled.port is None and reconciled.pid is None

    # … the endpoint disabled while the role binding survives …
    assert (await registry.get_endpoint(OWNER, endpoint.id)).enabled is False
    assert await registry.get_role(OWNER, "main") == [endpoint.id]

    # … and the orphan process was terminated.
    await asyncio.wait_for(orphan.wait(), timeout=5)
    assert orphan.returncode is not None


async def test_reconcile_is_a_noop_when_nothing_was_running(tmp_path: Path):
    service, _registry = await _service(tmp_path)
    # A stopped row is already terminal — reconcile must leave it untouched.
    row = await service._store.get_or_create(
        OWNER, EngineKind.llama_cpp, "acme/m", Workload.chat, None
    )
    await service._store.update(row.id, state=ServeState.stopped)

    await service.reconcile_on_startup()

    reconciled = await service._store.get(row.id)
    assert reconciled is not None and reconciled.state == ServeState.stopped.value
