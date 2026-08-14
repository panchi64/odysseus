"""The IMAP/SMTP adapter, driven against a stub ``aioimaplib`` client.

No live server: the point under test is the wire-response → domain-model translation and
the failure mapping (a refused login is an auth error, a dropped socket is an
unavailability the next call recovers from), all of which are ours.
"""

from __future__ import annotations

from dataclasses import dataclass

import aioimaplib
import pytest

from services.mail.errors import MailAuthError, MailError, MailUnavailableError
from services.mail.imap import ImapTransport, _first_literal, _parse_list_line, _search_uids
from services.mail.models import ROLE_SENT, ROLE_SPAM, AccountSpec

RAW = (
    b"From: Ada Lovelace <ada@example.org>\r\n"
    b"To: operator@example.com\r\n"
    b"Subject: Analytical Engine\r\n"
    b"Message-ID: <note-1@example.org>\r\n"
    b"Date: Thu, 13 Aug 2026 09:00:00 +0000\r\n"
    b"\r\n"
    b"The engine weaves algebraic patterns.\r\n"
)


@dataclass
class _Response:
    result: str
    lines: list


class _StubClient:
    """Just enough of ``aioimaplib.IMAP4_SSL`` for the adapter's command surface."""

    def __init__(self, *, login_ok: bool = True) -> None:
        self.login_ok = login_ok
        self.commands: list[tuple] = []
        self.selected: list[str] = []

    async def wait_hello_from_server(self) -> None:
        return None

    async def login(self, user, password):
        self.commands.append(("login", user))
        return _Response("OK" if self.login_ok else "NO", [])

    async def xoauth2(self, user, token):
        self.commands.append(("xoauth2", user, token))
        return _Response("OK" if self.login_ok else "NO", [])

    async def select(self, folder):
        self.selected.append(folder)
        return _Response("OK", [])

    async def list(self, reference, pattern):
        return _Response(
            "OK",
            [
                b'(\\HasNoChildren) "/" "INBOX"',
                b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"',
                b'(\\Noselect \\HasChildren) "/" "[Gmail]"',
                b'(\\HasNoChildren) "/" "Junk"',
            ],
        )

    async def uid_search(self, criteria):
        self.commands.append(("search", criteria))
        return _Response("OK", [b"1 2 3"])

    async def uid(self, verb, *args):
        self.commands.append((verb, *args))
        if verb == "fetch":
            return _Response("OK", [b"1 FETCH (FLAGS (\\Seen) RFC822.SIZE 120", RAW, b")"])
        return _Response("OK", [])

    async def expunge(self):
        self.commands.append(("expunge",))
        return _Response("OK", [])

    async def logout(self):
        return _Response("OK", [])


def _spec(**overrides) -> AccountSpec:
    fields = {
        "account_id": "a1",
        "address": "operator@example.com",
        "provider": "imap",
        "auth_kind": "password",
        "config": {
            "imap_host": "mail.example.com",
            "imap_port": 993,
            "smtp_host": "mail.example.com",
        },
        "password": "hunter2",
    }
    fields.update(overrides)
    return AccountSpec(**fields)


def _install(monkeypatch, client) -> None:
    monkeypatch.setattr(aioimaplib, "IMAP4_SSL", lambda **_kwargs: client)


async def test_probe_logs_in(monkeypatch):
    client = _StubClient()
    _install(monkeypatch, client)
    await ImapTransport(_spec()).probe()
    assert client.commands[0] == ("login", "operator@example.com")


async def test_an_oauth_account_authenticates_with_xoauth2(monkeypatch):
    client = _StubClient()
    _install(monkeypatch, client)
    await ImapTransport(_spec(auth_kind="oauth", access_token="ya29.token")).probe()
    assert client.commands[0] == ("xoauth2", "operator@example.com", "ya29.token")


async def test_a_refused_login_is_an_auth_error(monkeypatch):
    _install(monkeypatch, _StubClient(login_ok=False))
    with pytest.raises(MailAuthError):
        await ImapTransport(_spec()).probe()


async def test_an_unreachable_server_is_an_availability_error(monkeypatch):
    class _Dead(_StubClient):
        async def wait_hello_from_server(self):
            raise OSError("connection refused")

    _install(monkeypatch, _Dead())
    with pytest.raises(MailUnavailableError):
        await ImapTransport(_spec()).probe()


async def test_a_dropped_connection_is_retried_on_the_next_call(monkeypatch):
    class _Flaky(_StubClient):
        def __init__(self) -> None:
            super().__init__()
            self.fail_next_search = True

        async def uid_search(self, criteria):
            if self.fail_next_search:
                self.fail_next_search = False
                raise TimeoutError
            return await super().uid_search(criteria)

    client = _Flaky()
    _install(monkeypatch, client)
    transport = ImapTransport(_spec())
    with pytest.raises(MailUnavailableError):
        await transport.list_messages("INBOX")
    # The failed command dropped the cached connection, so this one logs in afresh.
    assert await transport.list_messages("INBOX")
    assert [c for c in client.commands if c[0] == "login"]


async def test_folders_carry_special_use_and_name_derived_roles(monkeypatch):
    _install(monkeypatch, _StubClient())
    folders = {f.id: f for f in await ImapTransport(_spec()).list_folders()}
    assert set(folders) == {"INBOX", "[Gmail]/Sent Mail", "Junk"}
    assert folders["[Gmail]/Sent Mail"].role == ROLE_SENT
    assert folders["[Gmail]/Sent Mail"].name == "Sent Mail"
    assert folders["Junk"].role == ROLE_SPAM  # no special-use flag — matched by name


async def test_listing_maps_wire_responses_to_headers(monkeypatch):
    _install(monkeypatch, _StubClient())
    headers = await ImapTransport(_spec()).list_messages("INBOX", limit=2)
    assert [h.uid for h in headers] == ["3", "2"]
    assert headers[0].sender.address == "ada@example.org"
    assert headers[0].sender.name == "Ada Lovelace"
    assert headers[0].subject == "Analytical Engine"
    assert headers[0].seen is True
    assert "algebraic patterns" in headers[0].snippet


async def test_incremental_listing_drops_the_boundary_uid(monkeypatch):
    client = _StubClient()
    _install(monkeypatch, client)
    headers = await ImapTransport(_spec()).list_messages("INBOX", since_uid="2")
    assert ("search", "UID 3:*") in client.commands
    assert [h.uid for h in headers] == ["3"]


async def test_fetch_returns_a_parsed_body(monkeypatch):
    _install(monkeypatch, _StubClient())
    body = await ImapTransport(_spec()).fetch("INBOX", "1")
    assert body.text.strip() == "The engine weaves algebraic patterns."
    assert body.header.message_id == "<note-1@example.org>"


async def test_flag_writes_only_the_requested_flags(monkeypatch):
    client = _StubClient()
    _install(monkeypatch, client)
    await ImapTransport(_spec()).flag("INBOX", "1", seen=True)
    stores = [c for c in client.commands if c[0] == "store"]
    assert stores == [("store", "1", "+FLAGS", "(\\Seen)")]


async def test_move_falls_back_to_copy_when_the_server_lacks_move(monkeypatch):
    class _NoMove(_StubClient):
        async def uid(self, verb, *args):
            if verb == "move":
                self.commands.append((verb, *args))
                return _Response("NO", [])
            return await super().uid(verb, *args)

    client = _NoMove()
    _install(monkeypatch, client)
    await ImapTransport(_spec()).move("INBOX", "1", "Archive")
    verbs = [c[0] for c in client.commands]
    assert verbs[-3:] == ["copy", "store", "expunge"]


async def test_a_missing_folder_is_a_domain_error(monkeypatch):
    class _NoFolder(_StubClient):
        async def select(self, folder):
            return _Response("NO", [])

    _install(monkeypatch, _NoFolder())
    with pytest.raises(MailError):
        await ImapTransport(_spec()).fetch("Nope", "1")


def test_response_parsing_helpers():
    assert _search_uids([b"* SEARCH", b"4 5 6"]) == ["4", "5", "6"]
    assert _search_uids([b"* SEARCH"]) == []
    assert _first_literal([b"1 FETCH (", RAW, b")"]) == RAW
    assert _first_literal([b")"]) is None
    assert _parse_list_line(b'(\\Noselect) "/" "[Gmail]"') is None
