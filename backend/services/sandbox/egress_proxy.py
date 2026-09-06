"""Allowlisting forward proxy — runs in a workspace's sidecar container, NOT the backend.

A workspace container is attached to an ``--internal`` network, so it has no route off
the host at all. This script is the single hole in that wall: it sits in a sidecar with
one leg on the workspace's internal network and one on ``bridge``, and it forwards only
what the workspace's allowlist names. Compute, installing packages and reaching a package
registry stay unrestricted; what is fenced is where bytes may *go*.

Two listeners, because the workspace container has no other way to be reached either:

* the proxy (``argv[1]``, 3128) — the workspace points ``HTTPS_PROXY`` at it;
* the forwarder (:data:`FORWARD_PORT`) — the one port this sidecar publishes to the
  operator's loopback, relaying to whichever preview container ``forward.txt`` names.
  A container on an internal network cannot publish a port (the runtime accepts
  ``--publish`` and silently maps nothing), and the sidecar can only because its bridge
  leg brings the mapping up; so the preview reaches the operator through here or not at
  all.

**Self-contained on purpose** — it is mounted read-only into a stock ``python`` image
with none of our code on its path, so it imports stdlib only and re-states the two
constants it shares with :mod:`services.egress` (a test asserts the pair never drifts).
The SSRF public-IP pinning is inherited from :mod:`services.webfetch.proxy_script`: an
allowlisted name that resolves to the operator's LAN is still a way back in.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import sys
from collections.abc import Iterable
from pathlib import Path

#: What the backend writes into the mounted directory (mirrors ``services.egress``).
ALLOW_FILE = "allow.txt"
#: Where the forwarder reads ``host:port`` for the workspace's live preview.
FORWARD_FILE = "forward.txt"
#: The published port the preview is reached on. Fixed, because it is baked into the
#: sidecar's ``--publish`` at creation, long before any preview exists.
FORWARD_PORT = 3129
#: Written into a refusal's body so a denial is legible in whatever the agent ran,
#: rather than an unexplained 403 from "some proxy".
DENIED_MARKER = "odysseus-egress: denied"

# Mirrors core.ssrf — keep in lockstep (a test enforces parity).
_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")  # RFC 6598 CGNAT / Tailscale
_METADATA_ADDRESSES = frozenset({"169.254.169.254", "fd00:ec2::254"})


def parse_allowlist(text: str) -> tuple[str, ...]:
    """The domains in an ``allow.txt``: one per line, blanks dropped, case folded."""
    return tuple(entry for line in text.splitlines() if (entry := line.strip().lower()))


def _allowed(host: str, domains: Iterable[str]) -> bool:
    """Whether ``host`` is covered by the allowlist.

    A plain entry covers the host itself *and* its subdomains — an operator who allowed
    ``example.com`` did not mean to leave ``www.example.com`` refused. A ``*.example.com``
    entry covers the subdomains only, which is the whole of what distinguishes the two
    forms: it is how an operator allows a CDN's shards without allowing its apex.
    """
    name = host.strip().rstrip(".").lower()
    for entry in domains:
        if entry.startswith("*."):
            base = entry[2:]
            if base and name.endswith(f".{base}"):
                return True
        elif name == entry or name.endswith(f".{entry}"):
            return True
    return False


class Allowlist:
    """The allowlist file, re-read whenever its mtime moves.

    Re-read rather than loaded once, because an approval's whole point is to unblock a
    request that is about to be retried — a proxy still holding the list as it stood at
    start-up would refuse that retry, which reads as an approval that did nothing. The
    backend replaces the file whole (a rename), so a reader sees one list or the other.
    """

    def __init__(self, directory: str) -> None:
        self._path = Path(directory) / ALLOW_FILE
        self._stamp: int | None = None
        self._domains: tuple[str, ...] = ()

    def domains(self) -> tuple[str, ...]:
        try:
            stamp = self._path.stat().st_mtime_ns
        except OSError:
            return ()  # no file yet ⇒ nothing is allowed (fail closed)
        if stamp != self._stamp:
            try:
                self._domains = parse_allowlist(self._path.read_text("utf-8"))
            except OSError:
                return ()
            self._stamp = stamp
        return self._domains


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or (ip.version == 4 and ip in _SHARED_ADDRESS_SPACE)
        or str(ip) in _METADATA_ADDRESSES
    )


async def _resolve_public_ips(host: str, port: int) -> list[str]:
    """Resolve ``host`` to the IPs to connect to, or raise if *any* of them is non-public
    (conservative: a split-horizon name with one private answer is refused). The caller
    dials a returned literal, which pins it — no second resolution to rebind."""
    loop = asyncio.get_running_loop()
    infos = await loop.run_in_executor(
        None, lambda: socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    )
    addrs: list[str] = []
    for info in infos:
        addr = str(info[4][0])
        if _is_blocked(ipaddress.ip_address(addr)):
            raise PermissionError(f"{addr} is non-public")
        if addr not in addrs:
            addrs.append(addr)
    if not addrs:
        raise OSError("did not resolve")
    return addrs


def _split_hostport(authority: str, default_port: int) -> tuple[str, int]:
    """Parse ``host:port`` (or a bare host), handling ``[ipv6]:port`` brackets."""
    if authority.startswith("["):
        host, _, rest = authority[1:].partition("]")
        port = int(rest[1:]) if rest.startswith(":") and rest[1:].isdigit() else default_port
        return host, port
    if ":" in authority:
        host, _, p = authority.rpartition(":")
        return host, int(p) if p.isdigit() else default_port
    return authority, default_port


async def _pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except OSError:
        pass
    finally:
        try:
            writer.close()
        except OSError:
            pass


async def _relay(client_r, client_w, server_r, server_w) -> None:
    await asyncio.gather(
        _pump(client_r, server_w), _pump(server_r, client_w), return_exceptions=True
    )


async def _respond(writer: asyncio.StreamWriter, status: str, body: str = "") -> None:
    payload = body.encode()
    head = (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: text/plain\r\nContent-Length: {len(payload)}\r\n"
        "Connection: close\r\n\r\n"
    )
    try:
        writer.write(head.encode() + payload)
        await writer.drain()
    except OSError:
        pass
    finally:
        writer.close()


async def _deny(writer: asyncio.StreamWriter, host: str) -> None:
    """Refuse a host the allowlist does not name, saying so in the body and on stdout.

    The body is what the agent actually sees — a bare 403 from an unnamed proxy is a
    dead end it would try to work around, while the marker names the fence and points at
    the request that widens it."""
    print(f"{DENIED_MARKER} {host}", flush=True)
    await _respond(writer, "403 Forbidden", f"{DENIED_MARKER} {host}\n")


async def _dial_pinned(host: str, port: int, client_w: asyncio.StreamWriter):
    """Resolve ``host``, refuse if non-public, then connect to a pinned public IP —
    trying each in order so an unreachable family doesn't dead-end a reachable one.
    Returns the upstream ``(reader, writer)``, or ``None`` after refusing ``client_w``."""
    try:
        ips = await _resolve_public_ips(host, port)
    except PermissionError:
        await _deny(client_w, host)  # allowlisted, but it points back inside
        return None
    except OSError:
        await _respond(client_w, "502 Bad Gateway")
        return None
    for ip in ips:
        try:
            return await asyncio.open_connection(host=ip, port=port)
        except OSError:
            continue
    await _respond(client_w, "502 Bad Gateway")
    return None


async def _handle_connect(authority: str, allow: Allowlist, client_r, client_w) -> None:
    host, port = _split_hostport(authority, 443)
    if not _allowed(host, allow.domains()):
        await _deny(client_w, host)
        return
    upstream = await _dial_pinned(host, port, client_w)
    if upstream is None:
        return
    server_r, server_w = upstream
    client_w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    await client_w.drain()
    await _relay(client_r, client_w, server_r, server_w)


async def _handle_http(
    method: str, target: str, version: str, allow: Allowlist, client_r, client_w
) -> None:
    # Absolute-form request line: `GET http://host/path HTTP/1.1`. Refuse anything else.
    scheme, marker, rest = target.partition("://")
    if not marker or scheme != "http":
        await _respond(client_w, "400 Bad Request")
        return
    authority, _, path = rest.partition("/")
    host, port = _split_hostport(authority, 80)
    # Read the rest of the request head; forward it origin-form, forcing a single request
    # per connection (Connection: close) so we needn't track keep-alive framing.
    # The client's own `Host:` is dropped and re-stated from the request line below: the
    # allowlist decision and the pinned dial are both made on the authority, and a shared
    # edge that routes by `Host:` would otherwise serve whatever *that* header named —
    # an approval for one domain answering as another is the one thing a name-based
    # fence cannot allow.
    head = bytearray()
    while (line := await client_r.readline()) not in (b"\r\n", b"", b"\n"):
        lower = line.lower()
        if lower.startswith((b"proxy-", b"connection:", b"host:")):
            continue
        head += line
    if not _allowed(host, allow.domains()):
        await _deny(client_w, host)
        return
    upstream = await _dial_pinned(host, port, client_w)
    if upstream is None:
        return
    server_r, server_w = upstream
    server_w.write(f"{method} /{path} {version}\r\n".encode())
    server_w.write(f"Host: {authority}\r\n".encode())
    server_w.write(bytes(head))
    server_w.write(b"Connection: close\r\n\r\n")
    await server_w.drain()
    await _relay(client_r, client_w, server_r, server_w)


def _peer_of(writer: asyncio.StreamWriter) -> str:
    peer = writer.get_extra_info("peername")
    return str(peer[0]) if peer else ""


def _in_subnets(address: str, subnets: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in net for net in subnets)


def _client_subnets() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """The networks a proxy client may dial in from, from ``EGRESS_CLIENT_SUBNET``.

    The sidecar keeps a leg on ``bridge`` — that leg is how it reaches the open web at
    all — and every other container on the host's default bridge can therefore address
    it. Without this check a container belonging to some other workspace could borrow
    this workspace's allowlist simply by pointing at its proxy.

    An unset or unparseable value yields nothing, and nothing refuses every peer: a
    control that disappears when its input is malformed is not a control."""
    raw = os.environ.get("EGRESS_CLIENT_SUBNET", "").replace(",", " ").split()
    nets = []
    for cidr in raw:
        try:
            nets.append(ipaddress.ip_network(cidr))
        except ValueError:
            continue
    return tuple(nets)


def _default_gateway() -> str:
    """This container's default route, which is the only peer the forwarder answers.

    Traffic arriving through the published loopback mapping is delivered by the runtime's
    own port forwarder, so it reaches us from the gateway of the bridge leg — the host
    itself, an address no container is ever assigned. Every *other* container on that
    bridge comes from a different address in the same subnet, which is exactly the borrow
    being refused, so a subnet test would be no test at all here."""
    try:
        lines = Path("/proc/net/route").read_text("utf-8").splitlines()[1:]
    except OSError:
        return ""
    for line in lines:
        fields = line.split()
        # Destination 0.0.0.0 with a non-zero gateway: the default route. Both are
        # little-endian hex, which is why the bytes are reversed before reading.
        if len(fields) > 2 and fields[1] == "00000000" and fields[2] != "00000000":
            try:
                return str(ipaddress.ip_address(bytes.fromhex(fields[2])[::-1]))
            except ValueError:
                continue
    return ""


def _dispatcher(allow: Allowlist, subnets):
    async def _dispatch(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
        try:
            if not _in_subnets(_peer_of(client_w), subnets):
                await _respond(client_w, "403 Forbidden", "odysseus-egress: not your proxy\n")
                return
            request_line = await client_r.readline()
            if not request_line:
                client_w.close()
                return
            parts = request_line.decode("latin-1").split()
            if len(parts) != 3:
                await _respond(client_w, "400 Bad Request")
                return
            method, target, version = parts
            if method.upper() == "CONNECT":
                # Discard the CONNECT headers before tunnelling (EOF ends the loop).
                while (await client_r.readline()) not in (b"\r\n", b"", b"\n"):
                    pass
                await _handle_connect(target, allow, client_r, client_w)
            else:
                await _handle_http(method, target, version, allow, client_r, client_w)
        except Exception:
            try:
                client_w.close()
            except OSError:
                pass

    return _dispatch


def _forwarder(directory: str):
    """Relay the published loopback port to whatever ``forward.txt`` currently names.

    Both the target *and* the gateway are read per connection rather than at start-up.
    The target because the sidecar comes up with the workspace, long before the agent
    starts a preview, and changes every time it starts another one. The gateway because
    this script boots with only the internal leg attached — a container on an internal
    network has no default route at all — and the bridge leg lands a moment later; a
    snapshot taken here would be empty for the sidecar's whole life, refusing every
    preview connection silently.

    No allowlist applies — what this reaches is the operator's own preview — but a peer
    check does. Publishing to ``127.0.0.1`` restricts nothing *inside* the container: the
    listener is on the bridge leg like everything else here, so without the check any
    container on the host's default bridge could open this workspace's dev server by the
    sidecar's address. Only :func:`_default_gateway` may, and an unknown gateway refuses
    everyone rather than letting the preview reopen the hole."""

    async def _forward(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
        gateway = _default_gateway()
        if not gateway or _peer_of(client_w) != gateway:
            client_w.close()
            return
        try:
            target = (Path(directory) / FORWARD_FILE).read_text("utf-8").strip()
        except OSError:
            target = ""
        if not target:
            client_w.close()
            return
        host, port = _split_hostport(target, 80)
        try:
            server_r, server_w = await asyncio.open_connection(host=host, port=port)
        except OSError:
            client_w.close()
            return
        await _relay(client_r, client_w, server_r, server_w)

    return _forward


async def main(port: int, directory: str) -> None:
    allow = Allowlist(directory)
    # 0.0.0.0, not loopback: both legs are other containers on this host's networks.
    # What keeps that from being an open relay is the peer check on each listener.
    proxy = await asyncio.start_server(_dispatcher(allow, _client_subnets()), "0.0.0.0", port)
    forward = await asyncio.start_server(_forwarder(directory), "0.0.0.0", FORWARD_PORT)
    # The owning process polls this line to know the fence is up (fail-closed: no
    # 'ready' ⇒ no workspace container is started behind it).
    print("PROXY-READY", flush=True)
    async with proxy, forward:
        await asyncio.gather(proxy.serve_forever(), forward.serve_forever())


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]), sys.argv[2]))
