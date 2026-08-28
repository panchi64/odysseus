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
    # A leftover endpoint from the "prior process": running and role-bound.
    endpoint = await registry.create_endpoint(
        OWNER,
        name="Local · acme/m",
        provider="local",
        managed=True,
        live_status="running",
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

    # … the endpoint marked not-running (the operator's switch untouched) while the
    # role binding survives …
    reconciled_endpoint = await registry.get_endpoint(OWNER, endpoint.id)
    assert reconciled_endpoint.live_status == "stopped"
    assert reconciled_endpoint.enabled is True
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


async def test_reconcile_stands_down_an_endpoint_its_row_no_longer_points_at(
    tmp_path: Path,
):
    """The row-driven sweep only sees non-terminal rows, so a serve that failed *after*
    its endpoint came up leaves the endpoint claiming to be running with nothing behind
    it. Resolution trusts that claim, so the stale endpoint has to be stood down on its
    own account — otherwise every request for its role dials a dead port until someone
    re-serves by hand."""
    service, registry = await _service(tmp_path)
    endpoint = await registry.create_endpoint(
        OWNER,
        name="Local · acme/m",
        provider="local",
        managed=True,
        live_status="running",
        base_url="http://127.0.0.1:9/v1",
        model="acme/m",
        native_tools=True,
    )
    await registry.set_role(OWNER, "main", [endpoint.id])
    row = await service._store.get_or_create(
        OWNER, EngineKind.llama_cpp, "acme/m", Workload.chat, None
    )
    # Terminal, so `active_rows` skips it — and the endpoint was never cleared.
    await service._store.update(row.id, state=ServeState.error, endpoint_id=endpoint.id)

    await service.reconcile_on_startup()

    reconciled = await registry.get_endpoint(OWNER, endpoint.id)
    assert reconciled.live_status == "stopped"
    assert reconciled.enabled is True  # the operator's own switch is untouched
    assert await registry.get_role(OWNER, "main") == [endpoint.id]


async def test_reconcile_leaves_unmanaged_endpoints_alone(tmp_path: Path):
    """An endpoint we don't serve is somebody else's process — its liveness is none of
    our business, and clearing it would bench a working remote endpoint on every boot."""
    service, registry = await _service(tmp_path)
    endpoint = await registry.create_endpoint(
        OWNER,
        name="Someone else's server",
        provider="local",
        managed=False,
        live_status="running",
        base_url="http://127.0.0.1:1234/v1",
    )

    await service.reconcile_on_startup()

    assert (await registry.get_endpoint(OWNER, endpoint.id)).live_status == "running"
