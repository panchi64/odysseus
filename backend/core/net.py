"""Loopback TCP readiness — wait for a subprocess to bind its port.

The shared probe behind every server we spawn and wait on: sandbox containers, the
managed SearXNG, the web-fetch browser, and local inference engines. Pure stdlib
asyncio with no domain coupling, so each caller wraps the timeout in its own error
(``SandboxError``, ``ServingError``, …).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress


async def await_listening(
    port: int,
    timeout_s: float,
    *,
    host: str = "127.0.0.1",
    poll_interval_s: float = 0.25,
    is_alive: Callable[[], bool] | None = None,
) -> None:
    """Poll ``host:port`` until a TCP connection succeeds.

    Raises ``TimeoutError`` if nothing is listening within ``timeout_s``. When
    ``is_alive`` is supplied and returns ``False`` (the process we're waiting on has
    already exited), raise ``ConnectionError`` immediately instead of waiting out the
    full timeout — so a server that dies on startup fails fast with a clear cause.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        if is_alive is not None and not is_alive():
            raise ConnectionError("the process exited before it started listening")
        try:
            _reader, writer = await asyncio.open_connection(host, port)
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()
            return
        except (OSError, ConnectionError):
            if loop.time() >= deadline:
                raise TimeoutError(
                    f"{host}:{port} did not start listening within {timeout_s:.0f}s"
                ) from None
            await asyncio.sleep(poll_interval_s)
