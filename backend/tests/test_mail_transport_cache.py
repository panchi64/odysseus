"""``MailService``'s per-account transport cache, and its one hard rule: a cached adapter
must never outlive the credentials it was built with.

An adapter snapshots its secret into an ``AccountSpec`` at construction and holds an
authenticated connection — it cannot be told that the account's access token rotated. The
service is the only layer that can notice, because ``MailSecrets.open_access`` is both the
sole reader of the sealed secret and the sole refresh path. Short-circuit the cache ahead
of it and every OAuth account fails an hour after its first use.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session

from core.db import in_session, init_db, make_engine
from core.vault import Vault
from models.mail import AUTH_OAUTH, PROVIDER_GMAIL, MailAccount
from services.credential_store import CredentialStore
from services.mail import service as mail_service
from services.mail.oauth import TokenBundle
from services.mail.service import MailService
from tests.mail_fakes import install_transport

EXPIRED = 1_000_000_000.0  # long past — `open_access` judges expiry against the real clock
LIVE = 4_000_000_000.0  # far future
LIVE_BUNDLE = TokenBundle(access_token="live", refresh_token="rt", expires_at=LIVE)


class _NoModels:
    async def resolve_background(self, **_kwargs):
        raise RuntimeError("no utility model configured")


class _SpecRecorder:
    """Stands in for a provider adapter, remembering the spec it was handed."""

    instances: list[_SpecRecorder] = []

    def __init__(self, spec) -> None:
        self.spec = spec
        self.closed = False
        _SpecRecorder.instances.append(self)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
async def wired(tmp_path, monkeypatch):
    """A service whose Gmail provider builds recorders instead of real adapters."""
    _SpecRecorder.instances = []
    monkeypatch.setitem(mail_service._TRANSPORTS, PROVIDER_GMAIL, _SpecRecorder)
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("pw")
    credentials = CredentialStore(engine, vault)
    await credentials.set_key("operator", "google_oauth", "client-secret")
    return MailService(engine, vault, credentials, _NoModels()), engine, vault


async def _oauth_account(service, engine, vault, bundle: TokenBundle) -> MailAccount:
    account = MailAccount(
        owner_id="operator",
        name="Personal",
        address_enc=vault.encrypt_str("operator@example.com"),
        provider=PROVIDER_GMAIL,
        auth_kind=AUTH_OAUTH,
        config={"oauth_provider": "google", "oauth_client_id": "client-id"},
        secret_enc=service._secrets.seal_bundle(bundle),
    )

    def work(session: Session) -> None:
        session.add(account)

    await in_session(engine, work)
    return account


async def test_a_live_token_reuses_the_cached_transport(wired, monkeypatch):
    """The cache still has to be a cache — one connection per account, not one per call."""
    service, engine, vault = wired
    account = await _oauth_account(service, engine, vault, LIVE_BUNDLE)

    async def _never(*_args, **_kwargs):
        raise AssertionError("a live token must not trigger a refresh")

    monkeypatch.setattr("services.mail.oauth.refresh_tokens", _never)
    first = await service._transport(account)
    assert await service._transport(account) is first
    assert len(_SpecRecorder.instances) == 1


async def test_every_call_resolves_credentials_before_consulting_the_cache(wired):
    """The load-bearing half, stated as its own rule: `open_access` runs on *every* call,
    not just a miss. It is the only code that notices an access token is near expiry and
    the only code that refreshes one, so a cache checked ahead of it pins the account to
    whatever token it happened to hold at build time. A cache hit is decided *after*.
    """
    service, engine, vault = wired
    account = await _oauth_account(service, engine, vault, LIVE_BUNDLE)
    opened = 0
    original = service._secrets.open_access

    async def counting(row):
        nonlocal opened
        opened += 1
        return await original(row)

    service._secrets.open_access = counting
    first = await service._transport(account)
    second = await service._transport(account)

    assert second is first  # still one connection...
    assert opened == 2  # ...but the credentials behind it were re-checked


async def test_a_rotated_token_rebuilds_the_transport(wired, monkeypatch):
    """The bug this guards: the adapter's token is frozen at construction, so a cache hit
    that skips `open_access` pins the account to a token that lapses within the hour and
    then fails every operation until the operator edits or probes the account."""
    service, engine, vault = wired
    account = await _oauth_account(
        service,
        engine,
        vault,
        TokenBundle(access_token="stale", refresh_token="rt-1", expires_at=EXPIRED),
    )

    async def _refresh(_provider, *, client_id, client_secret, refresh_token):
        return TokenBundle(access_token="fresh", refresh_token="rt-2", expires_at=LIVE)

    monkeypatch.setattr("services.mail.oauth.refresh_tokens", _refresh)
    stale = await service._transport(account)
    assert stale.spec.access_token == "fresh"  # the very first build already refreshed

    # Age the freshly-sealed bundle so the next call has to refresh again.
    account.secret_enc = service._secrets.seal_bundle(
        TokenBundle(access_token="fresh", refresh_token="rt-2", expires_at=EXPIRED)
    )

    async def _refresh_again(_provider, *, client_id, client_secret, refresh_token):
        return TokenBundle(access_token="fresher", refresh_token="rt-3", expires_at=LIVE)

    monkeypatch.setattr("services.mail.oauth.refresh_tokens", _refresh_again)
    rebuilt = await service._transport(account)

    assert rebuilt is not stale
    assert rebuilt.spec.access_token == "fresher"
    assert stale.closed is True  # the old connection is released, not leaked


async def test_an_installed_transport_is_cached_on_the_same_terms_as_a_built_one(wired):
    """Tests wire fakes in to keep the network out; `install_transport` records the same
    credentials the service would have, so an installed adapter is subject to the same
    rule rather than being an exception to it — nothing lands in the cache unaccounted
    for."""
    service, engine, vault = wired
    account = await _oauth_account(service, engine, vault, LIVE_BUNDLE)
    fake = _SpecRecorder(spec=None)
    await install_transport(service, "operator", account.id, fake)

    assert await service._transport(account) is fake
    assert service._transports[account.id].credentials == (None, "live")


async def test_dropping_a_transport_forgets_its_credentials(wired):
    service, engine, vault = wired
    account = await _oauth_account(service, engine, vault, LIVE_BUNDLE)
    first = await service._transport(account)
    await service._drop_transport(account.id)

    assert first.closed is True
    assert account.id not in service._transports
    assert await service._transport(account) is not first
