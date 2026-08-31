"""`park_for_approval`/`approval_conversation_title` in isolation: title wording,
grant-covered filtering, conversation-title lookup, and the "a notifier failure must
never break the park" guarantee — without driving a full model turn."""

from __future__ import annotations

from pydantic_ai import ToolApproved

from agent.parking import ParkedTurn, park_for_approval
from core.db import init_db, make_engine
from core.vault import Vault
from runs.run import Run, RunStatus
from runs.stream import RunStream
from services.conversations import ConversationStore
from services.notifications import NotificationService

OWNER = "operator"


class _FakeApproval:
    def __init__(self, tool_call_id: str, tool_name: str) -> None:
        self.tool_call_id = tool_call_id
        self.tool_name = tool_name

    def args_as_dict(self) -> dict:
        return {}


class _FakeRequests:
    def __init__(self, approvals: list[_FakeApproval]) -> None:
        self.approvals = approvals


def _run(conversation_id: str | None = "c1") -> Run:
    return Run(
        id="run-1", kind="chat", owner_id=OWNER, conversation_id=conversation_id, stream=RunStream()
    )


_APPROVALS = [
    _FakeApproval("call-1", "danger.delete_thing"),
    _FakeApproval("call-2", "danger.wipe_all"),
]


async def _notification_service(tmp_path) -> NotificationService:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("pw")
    service = NotificationService(engine, vault)
    await service.start()
    return service


async def test_park_names_conversation_and_pending_tools(tmp_path):
    service = await _notification_service(tmp_path)
    run = _run()

    await park_for_approval(
        run,
        None,
        [],
        _FakeRequests(_APPROVALS),
        set(),
        notifications=service,
        store=None,
        conversation_id="c1",
    )

    assert run.status is RunStatus.awaiting_input
    items, unread = await service.list_notifications(OWNER)
    assert unread == 1
    assert items[0].kind == "approval_needed"
    assert items[0].run_id == "run-1"
    assert items[0].conversation_id == "c1"
    assert "danger.delete_thing" in items[0].title
    assert "danger.wipe_all" in items[0].title
    await service.stop()


async def test_park_excludes_grant_covered_tool_names(tmp_path):
    service = await _notification_service(tmp_path)
    run = _run()

    await park_for_approval(
        run,
        None,
        [],
        _FakeRequests(_APPROVALS),
        set(),
        settled={"call-1": ToolApproved()},
        notifications=service,
        store=None,
        conversation_id="c1",
    )

    items, _ = await service.list_notifications(OWNER)
    assert len(items) == 1
    assert "danger.delete_thing" not in items[0].title
    assert "danger.wipe_all" in items[0].title
    await service.stop()


async def test_park_skips_notifying_when_every_call_is_grant_covered(tmp_path):
    service = await _notification_service(tmp_path)
    run = _run()

    await park_for_approval(
        run,
        None,
        [],
        _FakeRequests(_APPROVALS),
        set(),
        settled={"call-1": ToolApproved(), "call-2": ToolApproved()},
        notifications=service,
        store=None,
        conversation_id="c1",
    )

    assert run.status is RunStatus.awaiting_input  # still parks — just doesn't notify
    items, unread = await service.list_notifications(OWNER)
    assert items == []
    assert unread == 0
    await service.stop()


async def test_park_is_a_no_op_notify_when_notifications_is_none():
    run = _run()
    # Must not raise — a run without a wired notifier simply doesn't notify.
    await park_for_approval(
        run, None, [], _FakeRequests(_APPROVALS), set(), notifications=None, conversation_id="c1"
    )
    assert run.status is RunStatus.awaiting_input


async def test_park_uses_the_conversation_title_when_one_exists(tmp_path):
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "keyfile2.json")
    await vault.setup("pw")
    store = ConversationStore(engine, vault)
    await store.start()
    conv_id = await store.create_conversation(OWNER)
    await store.set_title(conv_id, "Refactor the widget")

    service = await _notification_service(tmp_path)
    run = _run(conversation_id=conv_id)

    await park_for_approval(
        run,
        None,
        [],
        _FakeRequests(_APPROVALS),
        set(),
        notifications=service,
        store=store,
        conversation_id=conv_id,
    )

    items, _ = await service.list_notifications(OWNER)
    assert "Refactor the widget" in items[0].title
    await store.stop()
    await service.stop()


async def test_park_falls_back_to_a_generic_label_without_a_title(tmp_path):
    service = await _notification_service(tmp_path)
    run = _run()

    # No store at all — title lookup degrades to the generic fallback rather than
    # failing the notify.
    await park_for_approval(
        run,
        None,
        [],
        _FakeRequests(_APPROVALS),
        set(),
        notifications=service,
        store=None,
        conversation_id="c1",
    )

    items, _ = await service.list_notifications(OWNER)
    assert "this conversation" in items[0].title
    await service.stop()


async def test_a_raising_notifier_never_breaks_the_park():
    class _RaisingNotifier:
        async def notify(self, *args, **kwargs):
            raise RuntimeError("boom")

    run = _run()
    # Must not raise — the parked run's own outcome must survive a notify failure.
    await park_for_approval(
        run,
        None,
        [],
        _FakeRequests(_APPROVALS),
        set(),
        notifications=_RaisingNotifier(),
        store=None,
        conversation_id="c1",
    )
    assert run.status is RunStatus.awaiting_input
    assert isinstance(run.parked_payload, ParkedTurn)
