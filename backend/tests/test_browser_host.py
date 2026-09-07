"""The host browser's bring-up — without ever opening a window.

``HostBrowser`` is three moving parts stitched together: an SSRF proxy that must be
listening *before* Chromium exists, a headed launch, and a debugging endpoint that appears
some time after the process does. All three are injected here, so what these tests
actually assert is the order, the arguments and the failure closure — the parts that would
otherwise only be discovered by watching a window open on the operator's screen.

The launch arguments are asserted rather than eyeballed because two of them are the egress
boundary: without ``--proxy-server`` the window reaches the internet unguarded, and
without the loopback bypass being switched off it reaches this very backend.
"""

from __future__ import annotations

import asyncio
import sys

from services.browser import HostBrowser
from services.browser import host as host_module

WS_URL = "ws://127.0.0.1:9333/devtools/browser/abc"


# --- fakes -----------------------------------------------------------------------------


class _FakeStdout:
    """The proxy's stdout: the lines it prints, then silence (a process still running)."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        await asyncio.sleep(3600)  # started, never listening — the deadline decides
        return b""


class _FakeProxy:
    def __init__(self, lines: list[bytes]) -> None:
        self.stdout = _FakeStdout(lines)
        self.returncode: int | None = None
        self.terminated = 0

    def terminate(self) -> None:
        self.terminated += 1
        self.returncode = -15

    async def wait(self) -> int | None:
        return self.returncode


class _FakeBrowser:
    def __init__(self) -> None:
        self.connected = True
        self.closed = 0

    def is_connected(self) -> bool:
        return self.connected

    async def close(self) -> None:
        self.closed += 1
        self.connected = False


class _FakeDriver:
    def __init__(self) -> None:
        self.stopped = 0

    async def stop(self) -> None:
        self.stopped += 1


class _Harness:
    """The three seams a ``HostBrowser`` takes, wired to fakes that record what it asked."""

    def __init__(
        self,
        *,
        proxy_lines: list[bytes] | None = None,
        ws_url: str | None = WS_URL,
    ) -> None:
        self._proxy_lines = [b"PROXY-READY\n"] if proxy_lines is None else proxy_lines
        self._ws_url = ws_url
        self.proxy_argv: list[list[str]] = []
        self.launch_args: list[list[str]] = []
        self.discovered: list[int] = []
        self.proxies: list[_FakeProxy] = []
        self.drivers: list[_FakeDriver] = []
        self.browsers: list[_FakeBrowser] = []

    async def spawn(self, argv) -> _FakeProxy:
        self.proxy_argv.append(list(argv))
        proxy = _FakeProxy(list(self._proxy_lines))
        self.proxies.append(proxy)
        return proxy

    async def launch(self, args) -> tuple[_FakeDriver, _FakeBrowser]:
        self.launch_args.append(list(args))
        driver, browser = _FakeDriver(), _FakeBrowser()
        self.drivers.append(driver)
        self.browsers.append(browser)
        return driver, browser

    async def discover(self, port: int, _timeout_s: float) -> str | None:
        self.discovered.append(port)
        return self._ws_url

    def build(self, **kwargs) -> HostBrowser:
        return HostBrowser(
            launcher=self.launch,
            spawner=self.spawn,
            discoverer=self.discover,
            **{"launch_timeout_s": 0.05} | kwargs,
        )


def _flag(args: list[str], prefix: str) -> str:
    matches = [arg.removeprefix(prefix) for arg in args if arg.startswith(prefix)]
    assert len(matches) == 1, f"expected exactly one {prefix} in {args}"
    return matches[0]


# --- bring-up --------------------------------------------------------------------------


async def test_nothing_is_launched_until_something_asks():
    # A window that appeared at boot would be a window in the way of every operator who
    # never browses in that session.
    fakes = _Harness()
    host = fakes.build()

    assert host.cdp_url is None
    assert (fakes.proxy_argv, fakes.launch_args) == ([], [])


async def test_the_window_is_launched_behind_its_own_proxy():
    fakes = _Harness()
    host = fakes.build()

    assert await host.ensure() == WS_URL

    argv = fakes.proxy_argv[0]
    assert argv[0] == sys.executable  # the interpreter, a fixed argv, no shell
    assert argv[1].endswith("proxy_script.py")
    args = fakes.launch_args[0]
    proxy_port = _flag(args, "--proxy-server=127.0.0.1:")
    assert proxy_port == argv[2]  # pointed at the proxy we actually started
    # Without this the page could reach the operator's own loopback — this backend
    # included — straight past the proxy.
    assert "--proxy-bypass-list=<-loopback>" in args
    cdp_port = _flag(args, "--remote-debugging-port=")
    assert cdp_port != proxy_port
    assert fakes.discovered == [int(cdp_port)]  # attached where we told it to listen


async def test_the_real_launch_keeps_chromium_sandboxed(monkeypatch):
    # The one assertion here that needs the real launcher rather than a seam: Playwright's
    # default for `chromium_sandbox` is off, and off means every page the agent opens
    # renders with no renderer sandbox, on the operator's own filesystem, with no container
    # under it any more. No browser is started — only the call is recorded.
    import playwright.async_api

    recorded: dict[str, object] = {}

    class _Chromium:
        async def launch(self, **kwargs) -> _FakeBrowser:
            recorded.update(kwargs)
            return _FakeBrowser()

    class _Driver(_FakeDriver):
        chromium = _Chromium()

    class _Starter:
        async def start(self) -> _Driver:
            return _Driver()

    monkeypatch.setattr(playwright.async_api, "async_playwright", _Starter)

    await host_module._launch_chromium(["--proxy-server=127.0.0.1:1"])  # noqa: SLF001

    assert recorded["chromium_sandbox"] is True
    assert recorded["headless"] is False


async def test_a_second_caller_joins_the_window_that_is_already_open():
    # Several browse tools in one model response race the first acquire of a thread; two
    # of them here would be two windows.
    fakes = _Harness()
    host = fakes.build()

    first, second = await asyncio.gather(host.ensure(), host.ensure())

    assert first == second == WS_URL
    assert len(fakes.launch_args) == 1


async def test_a_proxy_that_never_listens_means_no_browser_at_all():
    # Fail-closed: a window pointed at a dead proxy is a window with no egress guard, so
    # the launch is abandoned rather than completed without one.
    fakes = _Harness(proxy_lines=[])
    host = fakes.build()

    assert await host.ensure() is None
    assert fakes.launch_args == []  # never got as far as Chromium
    assert fakes.proxies[0].terminated == 1


async def test_a_window_whose_endpoint_never_appears_is_cleaned_up():
    fakes = _Harness(ws_url=None)
    host = fakes.build()

    assert await host.ensure() is None
    assert host.cdp_url is None
    assert fakes.browsers[0].closed == 1
    assert fakes.drivers[0].stopped == 1
    assert fakes.proxies[0].terminated == 1


# --- liveness --------------------------------------------------------------------------


async def test_a_quit_window_reports_no_endpoint():
    # This is how an operator closing Chromium reaches the session manager: `cdp_url`
    # going None is what its next sweep reaps every attached session on.
    fakes = _Harness()
    host = fakes.build()
    await host.ensure()

    fakes.browsers[0].connected = False

    assert host.cdp_url is None


async def test_a_dead_proxy_reports_no_endpoint():
    # The same fail-closed rule as the launch: the endpoint is never handed out while the
    # thing enforcing SSRF on it is gone.
    fakes = _Harness()
    host = fakes.build()
    await host.ensure()

    fakes.proxies[0].returncode = 1

    assert host.cdp_url is None


async def test_a_dead_host_is_closed_but_a_live_one_is_left_alone():
    # What the sweep calls when it finds the window gone: the proxy the window left
    # listening goes, but a window launched since the sweep looked is not torn down.
    fakes = _Harness()
    host = fakes.build()
    await host.ensure()

    await host.close_if_dead()
    assert fakes.proxies[0].terminated == 0

    fakes.browsers[0].connected = False
    await host.close_if_dead()

    assert fakes.proxies[0].terminated == 1
    assert fakes.drivers[0].stopped == 1


async def test_the_next_acquire_relaunches_after_the_operator_quits():
    fakes = _Harness()
    host = fakes.build()
    await host.ensure()
    fakes.browsers[0].connected = False

    assert await host.ensure() == WS_URL

    assert len(fakes.launch_args) == 2
    assert fakes.drivers[0].stopped == 1  # the abandoned pair went with it
    assert fakes.proxies[0].terminated == 1


async def test_stopping_closes_the_window_and_the_proxy():
    # Shutting the backend down must not leave a browser the operator has to hunt for.
    fakes = _Harness()
    host = fakes.build()
    await host.ensure()

    await host.stop()

    assert fakes.browsers[0].closed == 1
    assert fakes.drivers[0].stopped == 1
    assert fakes.proxies[0].terminated == 1
    assert host.cdp_url is None
