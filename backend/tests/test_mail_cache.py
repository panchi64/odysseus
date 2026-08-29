"""The inbox cache and the service that fronts it (`EMAIL-1`, `EMAIL-2`, `EMAIL-5`).

Everything here runs against the fake transport, so what's under test is ours: the
seal/open boundary, the freshness window, the reconciliation key, and the degrade-to-cache
behaviour when the provider is unreachable.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlmodel import Session, select

from core.db import in_session, init_db, make_engine
from core.vault import Vault
from models.mail import MailMessage
from services.credential_store import CredentialStore
from services.mail.errors import MailUnavailableError
from services.mail.models import MailAddress, MailBody
from services.mail.service import MailService
from services.mail.triage import TriageVerdict
from tests.mail_fakes import FakeTransport, install_transport, sample_header


class _NoModels:
    """A registry with nothing bound — every AI-assisted step must degrade, not fail."""

    async def resolve_background(self, **_kwargs):
        raise RuntimeError("no utility model configured")


@pytest.fixture
async def mail(tmp_path):
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("pw")
    service = MailService(engine, vault, CredentialStore(engine, vault), _NoModels())
    transport = FakeTransport()
    account = await service.create_account(
        "operator",
        name="Personal",
        address="operator@example.com",
        provider="imap",
        config={"imap_host": "mail.example.com"},
        password="hunter2",
    )
    # Inject the fake in place of a real connection — the seam is the whole point.
    await install_transport(service, "operator", account.id, transport)
    return service, account, transport, engine, vault


async def test_an_account_never_returns_its_secret(mail):
    service, account, _transport, _engine, _vault = mail
    assert account.has_secret is True
    assert "hunter2" not in repr(account)
    [listed] = await service.list_accounts("operator")
    assert listed.address == "operator@example.com"
    assert not hasattr(listed, "password")


async def test_message_content_is_sealed_at_rest(mail):
    service, account, _transport, engine, vault = mail
    await service.list_messages("operator", account_id=account.id)

    def read(session: Session) -> list[MailMessage]:
        return list(session.exec(select(MailMessage)).all())

    rows = await in_session(engine, read)
    assert rows
    row = rows[0]
    # Subject and sender are ciphertext on disk; the uid and timestamp are structural.
    assert "ada@example.org" not in row.from_address_enc
    assert vault.decrypt_str(row.from_address_enc) == "ada@example.org"
    assert row.uid in {"1", "2"}


async def test_the_listing_is_served_from_cache_inside_the_freshness_window(mail):
    service, account, transport, _engine, _vault = mail
    calls: list[str] = []
    original = transport.list_messages

    async def counted(folder, **kwargs):
        calls.append(folder)
        return await original(folder, **kwargs)

    transport.list_messages = counted
    await service.list_messages("operator", account_id=account.id)
    await service.list_messages("operator", account_id=account.id)
    assert len(calls) == 1  # the second read never touched the provider
    await service.list_messages("operator", account_id=account.id, refresh=True)
    assert len(calls) == 2


async def test_a_lapsed_window_re_consults_the_provider(tmp_path):
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "k.json")
    await vault.setup("pw")
    service = MailService(
        engine, vault, CredentialStore(engine, vault), _NoModels(), cache_ttl_s=-1.0
    )
    account = await service.create_account(
        "operator", name="P", address="op@example.com", password="x"
    )
    transport = FakeTransport()
    await install_transport(service, "operator", account.id, transport)
    calls: list[str] = []
    original = transport.list_messages

    async def counted(folder, **kwargs):
        calls.append(folder)
        return await original(folder, **kwargs)

    transport.list_messages = counted
    await service.list_messages("operator", account_id=account.id)
    await service.list_messages("operator", account_id=account.id)
    assert len(calls) == 2


async def test_an_unreachable_provider_degrades_to_the_cache(mail):
    service, account, transport, _engine, _vault = mail
    await service.list_messages("operator", account_id=account.id)

    async def dead(*_args, **_kwargs):
        raise MailUnavailableError("the server is down")

    transport.list_messages = dead
    cached = await service.list_messages("operator", account_id=account.id, refresh=True)
    assert [m.uid for m in cached] == ["2", "1"]


async def test_a_full_refresh_reconciles_flags_rather_than_duplicating(mail):
    service, account, transport, engine, _vault = mail
    await service.list_messages("operator", account_id=account.id, refresh=True)
    # The same two messages come back, one now read in another client.
    transport.messages["INBOX"][0] = MailBody(
        header=replace(sample_header("1"), seen=True), text="body of 1"
    )
    await service.list_messages("operator", account_id=account.id, refresh=True)

    def read(session: Session) -> list[MailMessage]:
        return list(session.exec(select(MailMessage)).all())

    rows = await in_session(engine, read)
    assert len(rows) == 2  # reconciled on (account, folder, uid)
    assert {row.uid: row.seen for row in rows}["1"] is True


async def test_a_background_pull_is_incremental(mail):
    """The cheap path asks only for what arrived after the newest cached uid — the
    reason a five-minute poll doesn't re-fetch the whole mailbox."""
    service, account, transport, _engine, _vault = mail
    await service.list_messages("operator", account_id=account.id, refresh=True)
    seen: list[str | None] = []
    original = transport.list_messages

    async def counted(folder, *, limit=50, since_uid=None):
        seen.append(since_uid)
        return await original(folder, limit=limit, since_uid=since_uid)

    transport.list_messages = counted
    await service._pull("operator", account.id, None)
    assert seen == ["2"]


async def test_reading_a_message_fetches_and_splits_its_body_once(mail):
    service, account, transport, _engine, _vault = mail
    transport.messages["INBOX"] = [
        MailBody(
            header=sample_header("1"),
            text="Yes, that works.\n\nOn Wed, Ada <ada@example.org> wrote:\n> Does Tuesday work?",
        )
    ]
    [view] = await service.list_messages("operator", account_id=account.id)
    fetches: list[str] = []
    original = transport.fetch

    async def counted(folder, uid):
        fetches.append(uid)
        return await original(folder, uid)

    transport.fetch = counted
    detail = await service.read_message("operator", view.id)
    assert detail.reply_text == "Yes, that works."
    assert detail.quoted_text is not None and "Does Tuesday work?" in detail.quoted_text
    await service.read_message("operator", view.id)
    assert fetches == ["1"]  # cached — the second open costs no round trip


async def test_flags_are_written_remotely_before_locally(mail):
    service, account, transport, _engine, _vault = mail
    [view] = (await service.list_messages("operator", account_id=account.id))[:1]
    await service.set_flags("operator", view.id, seen=True)
    assert transport.flagged == [("INBOX", view.uid, True, None)]
    refreshed = await service.cache.get("operator", view.id)
    assert refreshed.message.seen is True


async def test_a_failed_remote_flag_leaves_the_cache_honest(mail):
    service, account, transport, _engine, _vault = mail
    [view] = (await service.list_messages("operator", account_id=account.id))[:1]

    async def refused(*_args, **_kwargs):
        raise MailUnavailableError("the server is down")

    transport.flag = refused
    with pytest.raises(MailUnavailableError):
        await service.set_flags("operator", view.id, seen=True)
    assert (await service.cache.get("operator", view.id)).message.seen is False


async def test_triage_verdicts_are_stamped_and_filterable(mail):
    service, account, _transport, _engine, _vault = mail
    [view, _other] = await service.list_messages("operator", account_id=account.id)
    await service.cache.apply_triage(
        view.id, summary="Ada needs a decision", urgency="high", tags=["work"], spam=False
    )
    [top] = [m for m in await service.list_messages("operator") if m.id == view.id]
    assert (top.urgency, top.tags, top.summary) == ("high", ("work",), "Ada needs a decision")


async def test_spam_is_hidden_from_the_default_listing(mail):
    service, account, _transport, _engine, _vault = mail
    messages = await service.list_messages("operator", account_id=account.id)
    await service.cache.apply_triage(
        messages[0].id, summary="", urgency="low", tags=["promotion"], spam=True
    )
    visible = await service.list_messages("operator")
    assert messages[0].id not in {m.id for m in visible}
    with_spam = await service.list_messages("operator", include_spam=True)
    assert messages[0].id in {m.id for m in with_spam}


async def test_triage_degrades_when_no_model_is_bound(mail):
    service, account, _transport, _engine, _vault = mail
    [view] = (await service.list_messages("operator", account_id=account.id))[:1]
    detail = await service.read_message("operator", view.id)
    assert await service.triage.triage("operator", detail) is None


async def test_a_verdict_marks_the_message_triaged(mail):
    service, account, _transport, _engine, _vault = mail
    [view] = (await service.list_messages("operator", account_id=account.id))[:1]
    assert view.id in {d.message.id for d in await service.cache.untriaged("operator")}
    verdict = TriageVerdict(summary="s", category="work", urgency="normal", spam=False)
    await service.cache.apply_triage(
        view.id,
        summary=verdict.summary,
        urgency=verdict.urgency,
        tags=[verdict.category],
        spam=verdict.spam,
    )
    assert view.id not in {d.message.id for d in await service.cache.untriaged("operator")}


async def test_reply_threads_and_prefixes_the_subject(mail):
    service, account, transport, _engine, _vault = mail
    [view] = (await service.list_messages("operator", account_id=account.id))[:1]
    await service.reply("operator", view.id, "Agreed.")
    sent = transport.sent[0]
    assert [a.address for a in sent.to] == ["ada@example.org"]
    assert sent.subject.startswith("Re: ")
    assert sent.in_reply_to == view.message_id


async def test_reply_all_carries_the_cc_list(mail):
    service, account, transport, _engine, _vault = mail
    transport.messages["INBOX"] = [
        MailBody(
            header=replace(sample_header("1"), cc=(MailAddress(address="team@example.com"),)),
            text="hello",
        )
    ]
    [view] = await service.list_messages("operator", account_id=account.id, refresh=True)
    await service.reply("operator", view.id, "Agreed.", reply_all=True)
    assert [a.address for a in transport.sent[0].cc] == ["team@example.com"]


async def test_a_probe_records_operator_facing_health(mail):
    service, account, transport, _engine, _vault = mail
    healthy = await service.probe_account("operator", account.id)
    assert (healthy.status, healthy.error_detail) == ("ok", None)

    transport.probe_error = MailUnavailableError("could not reach the mail server")
    await install_transport(service, "operator", account.id, transport)
    broken = await service.probe_account("operator", account.id)
    assert broken.status == "error"
    assert "could not reach" in (broken.error_detail or "")


async def test_deleting_an_account_cascades_its_cached_mail(mail):
    service, account, _transport, engine, _vault = mail
    await service.list_messages("operator", account_id=account.id)
    await service.delete_account("operator", account.id)

    def read(session: Session) -> int:
        return len(list(session.exec(select(MailMessage)).all()))

    assert await in_session(engine, read) == 0
