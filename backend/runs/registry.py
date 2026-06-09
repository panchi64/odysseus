"""Pillar I — the RunRegistry: launch, track, bound, and cancel Runs.

In-process (D2): Runs are asyncio tasks tracked in a dict, gated by a global
concurrency semaphore (bursts queue at the gate — the ``queued`` state, also
satisfying TASK-5 "no overlapping overload"). The registry owns the lifecycle
mechanics — queued→running, the terminal-state mapping, the two timeout bounds
(XC-PERF-2), and cancellation — so every orchestrator inherits them for free.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from uuid import uuid4

from .events import RunEnded, RunError, RunMetrics, RunStarted, now_utc
from .run import Orchestrator, Run, RunStatus
from .stream import RunStream

_UNSET = object()


class RunTimeout(Exception):
    """A Run exceeded a bound. ``kind`` is ``wall_clock`` or ``inactivity``."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"{kind} timeout exceeded")
        self.kind = kind


class RunRegistry:
    def __init__(
        self,
        *,
        max_concurrency: int = 8,
        wall_clock_timeout_s: float | None = None,
        inactivity_timeout_s: float | None = None,
        max_retained: int = 200,
    ) -> None:
        self._runs: dict[str, Run] = {}
        self._sem = asyncio.Semaphore(max_concurrency)
        self._wall_clock = wall_clock_timeout_s
        self._inactivity = inactivity_timeout_s
        self._max_retained = max_retained

    # --- lookup ---------------------------------------------------------------
    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def list(self, owner_id: str | None = None) -> list[Run]:
        runs = list(self._runs.values())
        if owner_id is not None:
            runs = [r for r in runs if r.owner_id == owner_id]
        return runs

    # --- launch ---------------------------------------------------------------
    def submit(
        self,
        *,
        kind: str,
        owner_id: str,
        orchestrator: Orchestrator,
        run_id: str | None = None,
        wall_clock_timeout_s: float | None | object = _UNSET,
        inactivity_timeout_s: float | None | object = _UNSET,
    ) -> Run:
        run = Run(
            id=run_id or uuid4().hex,
            kind=kind,
            owner_id=owner_id,
            stream=RunStream(),
        )
        self._runs[run.id] = run
        self._evict_old()
        wall = self._wall_clock if wall_clock_timeout_s is _UNSET else wall_clock_timeout_s
        idle = self._inactivity if inactivity_timeout_s is _UNSET else inactivity_timeout_s
        run.task = asyncio.create_task(
            self._execute(run, orchestrator, wall, idle),  # type: ignore[arg-type]
            name=f"run:{run.id}",
        )
        return run

    async def cancel(self, run_id: str) -> bool:
        """Request cancellation; takes effect at the next await/step boundary."""
        run = self._runs.get(run_id)
        if run is None or run.is_terminal:
            return False
        run.cancel_requested = True
        if run.task is not None:
            run.task.cancel()
        return True

    # --- execution ------------------------------------------------------------
    async def _execute(
        self,
        run: Run,
        orchestrator: Orchestrator,
        wall_clock: float | None,
        inactivity: float | None,
    ) -> None:
        try:
            # Bursts wait here while ``queued`` — bounded concurrency (D2).
            async with self._sem:
                run.status = RunStatus.running
                run.started_at = now_utc()
                run.touch()
                run.emit(RunStarted(run_id=run.id, kind=run.kind))
                await self._supervise(run, orchestrator, wall_clock, inactivity)
                if not run.is_terminal:
                    run.status = RunStatus.done
                run.emit(run.metrics or RunMetrics())
                run.emit(RunEnded(outcome=run.status.value, detail=run.detail))
        except RunTimeout as timeout:
            run.status = RunStatus.error
            run.error = str(timeout)
            run.emit(RunError(message=str(timeout), kind=f"{timeout.kind}_timeout"))
        except asyncio.CancelledError:
            # The Run's own top-level handler turns cancellation into a recorded
            # terminal state rather than propagating it — intentional.
            run.status = RunStatus.cancelled
            run.emit(RunEnded(outcome="cancelled"))
        except Exception as exc:  # noqa: BLE001 — orchestrator failures are terminal, not fatal
            run.status = RunStatus.error
            run.error = str(exc)
            run.emit(RunError(message=str(exc), kind=type(exc).__name__))
        finally:
            run.ended_at = run.ended_at or now_utc()
            run.stream.close()

    async def _supervise(
        self,
        run: Run,
        orchestrator: Orchestrator,
        wall_clock: float | None,
        inactivity: float | None,
    ) -> None:
        """Run the orchestrator under wall-clock + inactivity bounds (XC-PERF-2)."""
        if not wall_clock and not inactivity:
            await orchestrator(run)
            return

        loop = asyncio.get_running_loop()
        main = asyncio.ensure_future(orchestrator(run))
        deadline = loop.time() + wall_clock if wall_clock else None
        try:
            while True:
                now = loop.time()
                waits: list[float] = []
                if deadline is not None:
                    waits.append(deadline - now)
                if inactivity is not None:
                    waits.append(run.last_activity_mono + inactivity - now)
                timeout = min(waits) if waits else None
                done, _ = await asyncio.wait(
                    {main}, timeout=max(0.0, timeout) if timeout is not None else None
                )
                if main in done:
                    main.result()  # propagate any orchestrator exception
                    return
                now = loop.time()
                if deadline is not None and now >= deadline:
                    raise RunTimeout("wall_clock")
                if inactivity is not None and now >= run.last_activity_mono + inactivity:
                    raise RunTimeout("inactivity")
        finally:
            if not main.done():
                main.cancel()
                with suppress(asyncio.CancelledError):
                    await main

    def _evict_old(self) -> None:
        """Bound memory: drop the oldest terminal runs past the retention cap."""
        terminal = [r for r in self._runs.values() if r.is_terminal]
        overflow = len(terminal) - self._max_retained
        if overflow <= 0:
            return
        terminal.sort(key=lambda r: r.ended_at or r.created_at)
        for run in terminal[:overflow]:
            self._runs.pop(run.id, None)
