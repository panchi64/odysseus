"""Lanes — the operator's turn never queues behind unattended work.

The bug this replaces was invisible rather than loud: one pool of eight slots, a
scheduled task and a few agent-opened research threads filling it, and the operator's
next message sitting at the gate looking exactly like a slow model. So what is pinned
here is the *separation*, not the numbers — that a saturated autonomous lane leaves the
interactive one untouched, and that every kind the composition path actually submits
under lands where it says it does.
"""

from __future__ import annotations

import asyncio

from runs import CHAT_TURN_KINDS, LANE_BY_KIND, LaneLimits, RunRegistry, RunStatus, lane_for


def _blocking(started: asyncio.Event, release: asyncio.Event):
    async def orchestrator(run) -> None:
        started.set()
        await release.wait()

    return orchestrator


async def test_an_unknown_kind_waits_in_the_unattended_lane():
    # A kind nobody mapped is far likelier to be new autonomous work than a turn someone
    # is waiting on, so the fallback must never be the operator's lane.
    assert lane_for("chat") == "interactive"
    assert lane_for("task") == "background"
    assert lane_for("linked") == "linked"
    assert lane_for("something-invented-later") == "background"


def test_every_composed_kind_has_a_lane():
    # `compose_turn` submits under these three; a fourth added without a lane would
    # silently inherit the unattended fallback.
    assert CHAT_TURN_KINDS == frozenset(LANE_BY_KIND)
    assert set(LANE_BY_KIND.values()) == {"interactive", "background", "linked"}


async def test_a_saturated_background_lane_does_not_queue_the_operators_turn():
    reg = RunRegistry(lanes=LaneLimits(interactive=1, background=1, linked=1))
    task_started, release_task = asyncio.Event(), asyncio.Event()
    linked_started, release_linked = asyncio.Event(), asyncio.Event()
    chat_started, release_chat = asyncio.Event(), asyncio.Event()

    task = reg.submit(
        kind="task", owner_id="operator", orchestrator=_blocking(task_started, release_task)
    )
    linked = reg.submit(
        kind="linked", owner_id="operator", orchestrator=_blocking(linked_started, release_linked)
    )
    second_task = reg.submit(
        kind="task", owner_id="operator", orchestrator=_blocking(asyncio.Event(), release_task)
    )
    await task_started.wait()
    await linked_started.wait()

    chat = reg.submit(
        kind="chat", owner_id="operator", orchestrator=_blocking(chat_started, release_chat)
    )
    # The interactive lane is empty, so this starts while both unattended lanes are full
    # and a second task is queued behind the first.
    await asyncio.wait_for(chat_started.wait(), timeout=1.0)
    assert chat.status is RunStatus.running
    assert second_task.status is RunStatus.queued

    release_chat.set()
    release_task.set()
    release_linked.set()
    for run in (chat, task, linked, second_task):
        await run.wait()
    assert all(run.status is RunStatus.done for run in (chat, task, linked, second_task))


async def test_two_interactive_turns_still_share_their_own_lane():
    # Splitting the pool must not accidentally make the operator's lane unbounded.
    reg = RunRegistry(lanes=LaneLimits(interactive=1))
    first_started, release = asyncio.Event(), asyncio.Event()

    first = reg.submit(
        kind="chat", owner_id="operator", orchestrator=_blocking(first_started, release)
    )
    second = reg.submit(
        kind="chat", owner_id="operator", orchestrator=_blocking(asyncio.Event(), release)
    )
    await first_started.wait()
    assert second.status is RunStatus.queued

    release.set()
    await first.wait()
    await second.wait()
