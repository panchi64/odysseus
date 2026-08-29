"""Manifest discovery/order, the service container, and the run-terminal dispatch."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from harness.discovery import discover_manifests, order_manifests
from harness.manifest import FeatureManifest, ServiceContainer
from harness.run_terminal import RunTerminalDispatcher


def test_order_respects_after_edges_and_breaks_ties_by_name():
    manifests = [
        FeatureManifest(name="tasks", after=("uploads",)),
        FeatureManifest(name="corpus"),
        FeatureManifest(name="uploads", after=("corpus",)),
        FeatureManifest(name="memory"),
    ]
    ordered = [m.name for m in order_manifests(manifests)]
    assert ordered.index("corpus") < ordered.index("uploads") < ordered.index("tasks")
    assert ordered[:2] == ["corpus", "memory"]  # the tie is name-sorted, not input-sorted


def test_order_rejects_duplicates_and_unknown_edges():
    with pytest.raises(ValueError, match="duplicate"):
        order_manifests([FeatureManifest(name="a"), FeatureManifest(name="a")])
    with pytest.raises(ValueError, match="unknown"):
        order_manifests([FeatureManifest(name="a", after=("ghost",))])


def test_discovered_manifests_are_valid_and_ordered():
    """Whatever lives in harness/manifests/ right now: unique names, known edges,
    every `after` producer strictly before its consumer."""
    manifests = discover_manifests()
    seen: set[str] = set()
    for manifest in manifests:
        assert set(manifest.after) <= seen, f"{manifest.name} builds before a dependency"
        seen.add(manifest.name)


def test_provider_assembly_order_is_deterministic_and_doc_state_is_prompt_context():
    """The assembled instruction/prompt-context provider order is pinned by discovery
    (topo + name-sorted ties) — instructions render at the head of every request, so a
    provider order that varied between boots would silently invalidate the inference
    engine's cached prompt prefix."""
    first = discover_manifests()
    second = discover_manifests()
    assert [m.name for m in first] == [m.name for m in second]
    assert [m.instructions for m in first] == [m.instructions for m in second]
    assert [m.prompt_context for m in first] == [m.prompt_context for m in second]


class _Memory:
    pass


def test_container_get_is_loud_and_optional_is_quiet():
    container = ServiceContainer()
    with pytest.raises(LookupError, match="_Memory"):
        container.get(_Memory)
    assert container.get_optional(_Memory) is None
    instance = _Memory()
    container.add(instance)
    assert container.get(_Memory) is instance
    with pytest.raises(LookupError, match="already registered"):
        container.add(_Memory())


@dataclass
class _FakeStream:
    subscriber_count: int = 0


@dataclass
class _FakeRun:
    id: str = "run-1"
    stream: _FakeStream = field(default_factory=_FakeStream)


async def test_dispatcher_runs_sync_inline_then_async_as_tracked_tasks():
    dispatcher = RunTerminalDispatcher()
    log: list[str] = []
    dispatcher.add_sync(lambda run: log.append(f"sync:{run.id}"))

    async def notice(run, watched):
        log.append(f"async:{run.id}:watched={watched}")

    dispatcher.add(notice)
    run = _FakeRun(stream=_FakeStream(subscriber_count=2))
    dispatcher(run)
    assert log == ["sync:run-1"]  # sync ran inline; async is scheduled, not run
    assert len(dispatcher.tasks) == 1
    await asyncio.gather(*dispatcher.tasks)
    assert log == ["sync:run-1", "async:run-1:watched=True"]


async def test_dispatcher_isolates_hook_failures():
    dispatcher = RunTerminalDispatcher()
    log: list[str] = []

    def bad_sync(run):
        raise RuntimeError("sync boom")

    async def bad_async(run, watched):
        raise RuntimeError("async boom")

    async def good(run, watched):
        log.append("good")

    dispatcher.add_sync(bad_sync)
    dispatcher.add(bad_async)
    dispatcher.add(good)
    dispatcher(_FakeRun())
    await asyncio.gather(*dispatcher.tasks)
    assert log == ["good"]


async def test_dispatcher_drain_cancels_pending_tasks():
    dispatcher = RunTerminalDispatcher()
    parked = asyncio.Event()

    async def forever(run, watched):
        parked.set()
        await asyncio.Event().wait()

    dispatcher.add(forever)
    dispatcher(_FakeRun())
    await parked.wait()
    await dispatcher.drain()
    assert not dispatcher.tasks
