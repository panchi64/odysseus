"""The allowlist predicate the container fence is made of, and the file it reads it from.

The script under test runs in a stock python image with none of our code on its path, so
it re-states the constants it shares with the policy that writes the file. That makes
drift a real failure mode rather than a theoretical one — hence the parity checks here.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os

import services.egress as egress_mod
import services.sandbox.egress_proxy as proxy_mod
from services.sandbox.egress_proxy import (
    ALLOW_FILE,
    DENIED_MARKER,
    Allowlist,
    _allowed,
    _client_subnets,
    parse_allowlist,
)

from .conftest import egress_policy


# --- the predicate ----------------------------------------------------------
def test_a_plain_domain_covers_the_host_and_its_subdomains():
    assert _allowed("pypi.org", ["pypi.org"])
    assert _allowed("files.pypi.org", ["pypi.org"])
    assert _allowed("a.b.pypi.org", ["pypi.org"])


def test_a_plain_domain_does_not_cover_a_lookalike_suffix():
    # The check that matters: `notpypi.org` ends with `pypi.org` as a *string*, and a
    # naive suffix test would hand an approval for one host to a domain anyone can buy.
    assert not _allowed("notpypi.org", ["pypi.org"])
    assert not _allowed("pypi.org.evil.com", ["pypi.org"])
    assert not _allowed("example.com", ["pypi.org"])


def test_a_wildcard_covers_subdomains_only():
    assert _allowed("cdn.example.com", ["*.example.com"])
    assert _allowed("a.b.example.com", ["*.example.com"])
    assert not _allowed("example.com", ["*.example.com"])  # the apex was not approved


def test_matching_ignores_case_and_the_dns_root_dot():
    assert _allowed("PyPI.ORG.", ["pypi.org"])


def test_an_empty_allowlist_allows_nothing():
    assert not _allowed("pypi.org", [])


# --- the file ---------------------------------------------------------------
def test_parse_allowlist_takes_one_domain_per_line():
    assert parse_allowlist("pypi.org\n*.example.com\n") == ("pypi.org", "*.example.com")
    assert parse_allowlist("\n  pypi.org  \n\n") == ("pypi.org",)
    assert parse_allowlist("PyPI.org\n") == ("pypi.org",)
    assert parse_allowlist("") == ()


def test_the_allowlist_reloads_when_the_file_changes(tmp_path):
    # An approval exists to unblock a retry that is about to happen. A proxy still
    # holding the list as it stood at start-up would refuse that retry — which reads,
    # to whoever is watching, as an approval that did nothing.
    path = tmp_path / ALLOW_FILE
    path.write_text("pypi.org\n")
    allow = Allowlist(str(tmp_path))
    assert allow.domains() == ("pypi.org",)

    path.write_text("pypi.org\napi.example.com\n")
    os.utime(path, (1, 1))  # a distinct mtime, whatever the filesystem's resolution
    assert allow.domains() == ("pypi.org", "api.example.com")


def test_a_missing_allowlist_fails_closed(tmp_path):
    assert Allowlist(str(tmp_path)).domains() == ()


# --- parity with the policy that writes the file ----------------------------
def test_the_script_and_the_policy_name_the_same_file():
    # The script cannot import the policy (it runs with none of our code on its path),
    # so the constant is written twice and this is what keeps the two spellings one file.
    assert ALLOW_FILE == egress_mod.ALLOW_FILE


async def test_the_policys_own_output_parses_and_matches(tmp_path):
    # End to end over the real seam: what `EgressPolicy` writes is what the fence reads.
    policy = egress_policy(tmp_path, ("pypi.org", "*.example.com"))
    await policy.materialise("conv-1")
    domains = Allowlist(str(policy.allow_dir("conv-1"))).domains()

    assert _allowed("files.pypi.org", domains)
    assert _allowed("cdn.example.com", domains)
    assert not _allowed("evil.com", domains)


def test_the_denial_marker_names_this_fence():
    # It is what an agent sees in the body of a refusal, so it has to identify the fence
    # rather than read as an anonymous proxy error it would try to work around.
    assert DENIED_MARKER.startswith("odysseus-egress")


def test_the_blocklist_matches_core_ssrf():
    # The sidecar runs with none of our code on its path, so it carries a copy of the SSRF
    # predicate. This is the test the copy's own comment promises: without it the source
    # of truth can gain a range and this proxy keep dialling it.
    from core import ssrf as core_ssrf

    for sample in (
        "8.8.8.8",
        "93.184.216.34",
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "224.0.0.1",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "2606:4700:4700::1111",
        "fd00:ec2::254",
    ):
        ip = ipaddress.ip_address(sample)
        assert proxy_mod._is_blocked(ip) == core_ssrf._is_blocked(ip), sample


# --- the peer check: whose proxy this is ------------------------------------
async def _dispatch_once(directory, subnets, raw: bytes) -> bytes:
    """One request through the proxy's dispatcher over loopback; the reply it wrote."""
    handler = proxy_mod._dispatcher(Allowlist(str(directory)), subnets)
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(raw)
        await writer.drain()
        reply = await asyncio.wait_for(reader.read(65536), timeout=5.0)
        writer.close()
    return reply


async def test_a_peer_outside_the_workspace_network_is_refused(tmp_path):
    # The sidecar keeps a leg on the host's default bridge, so every other container
    # there can address its proxy. Only this workspace's own network may use it.
    (tmp_path / ALLOW_FILE).write_text("pypi.org\n")
    reply = await _dispatch_once(
        tmp_path,
        (ipaddress.ip_network("172.31.0.0/16"),),
        b"GET http://pypi.org/simple HTTP/1.1\r\n\r\n",
    )
    assert b"403" in reply and b"not your proxy" in reply


async def test_an_unreadable_client_subnet_refuses_every_peer(tmp_path):
    # Fail closed: a subnet the runtime never reported (or reported in a shape this
    # template does not fit) must not turn the check into a no-op — that is precisely
    # when the proxy would be an open relay for anything on the bridge.
    (tmp_path / ALLOW_FILE).write_text("pypi.org\n")
    reply = await _dispatch_once(tmp_path, (), b"GET http://pypi.org/simple HTTP/1.1\r\n\r\n")
    assert b"403" in reply and b"not your proxy" in reply


def test_client_subnets_drops_what_it_cannot_parse(monkeypatch):
    monkeypatch.setenv("EGRESS_CLIENT_SUBNET", "172.31.0.0/16 not-a-subnet")
    assert _client_subnets() == (ipaddress.ip_network("172.31.0.0/16"),)
    monkeypatch.delenv("EGRESS_CLIENT_SUBNET")
    assert _client_subnets() == ()


async def test_the_forwarded_host_header_names_the_authority_that_was_allowed(
    tmp_path, monkeypatch
):
    # The allowlist decision and the pinned dial are both made on the request line's
    # authority. A `Host:` the agent chose freely would let an approved name reach a
    # different origin on any edge that routes by it — the check and the request have
    # to name the same host.
    seen: list[bytes] = []

    async def upstream(reader, writer):
        seen.append(await reader.read(65536))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await writer.drain()
        writer.close()

    up = await asyncio.start_server(upstream, "127.0.0.1", 0)
    up_port = up.sockets[0].getsockname()[1]

    async def fake_dial(_host, _port, _client_w):
        return await asyncio.open_connection("127.0.0.1", up_port)

    monkeypatch.setattr(proxy_mod, "_dial_pinned", fake_dial)
    (tmp_path / ALLOW_FILE).write_text("pypi.org\n")
    async with up:
        await _dispatch_once(
            tmp_path,
            (ipaddress.ip_network("127.0.0.0/8"),),
            b"GET http://pypi.org/simple HTTP/1.1\r\nHost: attacker.example\r\n\r\n",
        )

    head = seen[0].decode()
    assert "Host: pypi.org\r\n" in head
    assert "attacker.example" not in head
