"""The execution-sandbox capability — interface, value types, and errors.

Every bit of agent-invoked code or shell execution runs *through* this interface,
isolated from the host. The invariant the interface promises: the executed code
sees only **copies** of the files explicitly handed to it (``SandboxSpec.files``),
cannot read or modify the host filesystem / processes / environment, and has
**network egress off by default** (``SandboxSpec.network``). Outputs return
explicitly (stdout/stderr + copied-out files); nothing escapes the box as a side
effect.

Pluggable by design: :class:`Sandbox` is the seam, the default backend is a
container runtime (``container.ContainerSandbox``), and a fake is injected in
tests. The factory in ``detect.py`` **fails closed** — if no backend is available
the capability is *absent* (``None``), never a silent host fallback.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from core.exceptions import OdysseusError


class SandboxError(OdysseusError):
    """The sandbox backend failed to run the request (not a non-zero exit — that
    is an ordinary :class:`SandboxResult` the agent acts on). This is an
    infrastructure failure: the runtime vanished, the image is missing, the
    container could not start."""


@dataclass(frozen=True)
class SandboxFile:
    """A file copied *into* the box before execution — a copy of an operator
    file, never the original. ``path`` is relative to the working directory."""

    path: str
    content: bytes


@dataclass(frozen=True)
class SandboxSpec:
    """One isolated execution request.

    ``command`` is an argv run inside the box's working directory (e.g.
    ``["python", "-c", code]`` or ``["bash", "-c", script]``). ``files`` are
    copied in; ``outputs`` names files to copy back out after the run. ``env`` is
    the *only* environment the process sees — the host environment never leaks in.
    """

    command: Sequence[str]
    files: Sequence[SandboxFile] = ()
    outputs: Sequence[str] = ()
    stdin: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    timeout_s: float = 30.0
    network: bool = False  # egress off by default so copied data can't leak


@dataclass(frozen=True)
class SandboxResult:
    """What an isolated run produced. A non-zero ``exit_code`` or a ``timed_out``
    run is a normal result the agent reasons about — not an error."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    outputs: Mapping[str, bytes] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class Sandbox(ABC):
    """A host-isolated execution backend. Implementations honor the invariant in
    the module docstring; the contract is just :meth:`run` over a spec."""

    #: A short, stable name for the backend (surfaced to the operator/logs).
    name: str = "sandbox"

    @abstractmethod
    async def available(self) -> bool:
        """Whether this backend can actually run right now (the runtime is
        present and responsive). The factory uses it to fail closed."""

    @abstractmethod
    async def run(self, spec: SandboxSpec) -> SandboxResult:
        """Execute ``spec`` in isolation and return its result. Raises
        :class:`SandboxError` only on infrastructure failure."""
