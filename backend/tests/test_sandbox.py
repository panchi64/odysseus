"""The execution-sandbox capability: fail-closed detection, container hardening,
copy in/out, and the deliberate host escape hatch."""

from __future__ import annotations

import asyncio
import subprocess

import pytest

from core.config import Settings
from services.sandbox import (
    ContainerSandbox,
    SandboxError,
    SandboxFile,
    SandboxResult,
    SandboxSpec,
    detect_sandbox,
    run_on_host,
)
from services.sandbox.container import (
    discover_runtime,
    hardened_flags,
    prepare_workspace,
    workspace_env_defaults,
)


def _runtime_ready() -> bool:
    """A runtime binary on PATH *and* a reachable daemon — the real gate for the
    integration tests (a present CLI with a dead daemon must still skip)."""
    runtime = discover_runtime()
    if runtime is None:
        return False
    try:
        proc = subprocess.run(
            [runtime, "version"], capture_output=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


# --- result/value types ------------------------------------------------------
def test_result_ok_only_when_clean_exit():
    assert SandboxResult(exit_code=0, stdout="", stderr="").ok
    assert not SandboxResult(exit_code=1, stdout="", stderr="").ok
    assert not SandboxResult(exit_code=0, stdout="", stderr="", timed_out=True).ok


# --- fail-closed detection (the one safety rule) -----------------------------
async def test_detect_disabled_returns_none():
    assert await detect_sandbox(Settings(sandbox_enabled=False)) is None


async def test_detect_returns_none_when_no_runtime(monkeypatch):
    # No backend available ⇒ capability absent, never a host fallback.
    monkeypatch.setattr(ContainerSandbox, "available", lambda self: _false())
    assert await detect_sandbox(Settings(sandbox_enabled=True)) is None


async def test_detect_returns_backend_when_available(monkeypatch):
    monkeypatch.setattr(ContainerSandbox, "available", lambda self: _true())
    sandbox = await detect_sandbox(Settings(sandbox_enabled=True))
    assert isinstance(sandbox, ContainerSandbox)


async def _false() -> bool:
    return False


async def _true() -> bool:
    return True


# --- container command construction (host shut out by construction) ----------
def test_run_argv_is_locked_down_by_default(tmp_path):
    sandbox = ContainerSandbox(runtime="docker", image="img:1")
    argv = sandbox._run_argv("docker", SandboxSpec(command=["echo", "hi"]), tmp_path)
    joined = " ".join(argv)
    assert "--network none" in joined  # egress off by default
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--read-only" in joined
    assert "--pids-limit 256" in joined
    assert f"{tmp_path}:/work" in joined  # copies mounted, not host files
    # The command is preserved verbatim at the tail, wrapped by the in-container
    # timeout, which the image precedes.
    assert argv[-2:] == ["echo", "hi"]
    assert argv[argv.index("img:1") + 1] == "timeout"  # enforced inside the box
    assert "--kill-after=5" in joined


def test_run_argv_opens_network_only_when_asked(tmp_path):
    sandbox = ContainerSandbox(runtime="podman")
    argv = sandbox._run_argv("podman", SandboxSpec(command=["x"], network=True), tmp_path)
    assert "--network bridge" in " ".join(argv)


def test_env_is_explicit_only(tmp_path):
    sandbox = ContainerSandbox(runtime="docker")
    spec = SandboxSpec(command=["x"], env={"FOO": "bar"})
    argv = sandbox._run_argv("docker", spec, tmp_path)
    assert "--env FOO=bar" in " ".join(argv)


# --- package installs redirect to the writable workspace ---------------------
def test_workspace_env_defaults_point_under_the_workdir():
    env = workspace_env_defaults("/work")
    # Installs, caches, and build temp all land in the writable bind-mount.
    assert env["PIP_USER"] == "1"
    assert env["PYTHONUSERBASE"] == "/work/.local"
    assert env["PIP_CACHE_DIR"].startswith("/work/")
    assert env["TMPDIR"].startswith("/work/")
    # Console scripts on PATH, but python/pip still resolve from the image.
    assert env["PATH"].startswith("/work/.local/bin:")
    assert "/usr/local/bin" in env["PATH"]


def test_hardened_flags_inject_install_redirects(tmp_path):
    joined = " ".join(
        hardened_flags(
            network=False,
            memory="512m",
            cpus="1.0",
            pids_limit=256,
            workdir="/work",
            mount=tmp_path,
            env={},
        )
    )
    assert "--env PIP_USER=1" in joined
    assert "--env PYTHONUSERBASE=/work/.local" in joined


def test_explicit_env_overrides_a_default(tmp_path):
    flags = hardened_flags(
        network=False,
        memory="512m",
        cpus="1.0",
        pids_limit=256,
        workdir="/work",
        mount=tmp_path,
        env={"PIP_USER": "0"},
    )
    joined = " ".join(flags)
    assert "PIP_USER=0" in joined
    assert "PIP_USER=1" not in joined  # the caller's value wins, not duplicated


def test_prepare_workspace_creates_the_tmpdir(tmp_path):
    # TMPDIR must pre-exist or mktemp fails and tempfile falls back to the small
    # tmpfs; the env points at "<workdir>/.tmp", so that subdir must be created.
    target = workspace_env_defaults("/work")["TMPDIR"]
    assert target == "/work/.tmp"
    prepare_workspace(tmp_path)
    assert (tmp_path / ".tmp").is_dir()
    # Idempotent — a second call over an existing workspace is fine.
    prepare_workspace(tmp_path)
    assert (tmp_path / ".tmp").is_dir()


# --- copy in / copy out ------------------------------------------------------
def test_write_and_read_files_round_trip(tmp_path):
    spec = SandboxSpec(
        command=["x"],
        files=[SandboxFile(path="in.txt", content=b"hello")],
        outputs=["out.txt"],
    )
    ContainerSandbox._write_inputs(tmp_path, spec)
    assert (tmp_path / "in.txt").read_bytes() == b"hello"
    # Only a file that exists is read back; a named-but-missing output is skipped.
    assert ContainerSandbox._read_outputs(tmp_path, spec) == {}
    (tmp_path / "out.txt").write_bytes(b"result")
    assert ContainerSandbox._read_outputs(tmp_path, spec) == {"out.txt": b"result"}


def test_input_path_cannot_escape_the_box(tmp_path):
    spec = SandboxSpec(command=["x"], files=[SandboxFile(path="../escape", content=b"x")])
    with pytest.raises(SandboxError):
        ContainerSandbox._write_inputs(tmp_path, spec)


# --- the deliberate host escape hatch ----------------------------------------
async def test_run_on_host_executes_and_reports_exit():
    ok = await run_on_host("echo hostran")
    assert ok.ok and "hostran" in ok.stdout
    bad = await run_on_host("exit 3")
    assert bad.exit_code == 3 and not bad.ok


async def test_host_timeout_kills_the_whole_process_group(tmp_path):
    # A child the command backgrounds must die with the timeout, not orphan.
    marker = tmp_path / "orphan-ran"
    cmd = f"( sleep 2; touch {marker} ) & wait"
    result = await run_on_host(cmd, timeout_s=0.4)
    assert result.timed_out and result.exit_code == 124
    await asyncio.sleep(2.5)  # past when an orphaned child would have written
    assert not marker.exists()  # the whole group was killed — no survivor


# --- container integration (only when a real runtime is present) -------------
@pytest.mark.skipif(not _runtime_ready(), reason="no usable container runtime")
async def test_container_runs_python_in_isolation():
    sandbox = ContainerSandbox()
    result = await sandbox.run(
        SandboxSpec(command=["python", "-c", "print(6 * 7)"], timeout_s=60)
    )
    assert result.ok
    assert result.stdout.strip() == "42"


# Resolving a public name proves egress; the same call fails closed without it.
_DNS_PROBE = "import socket; socket.gethostbyname('pypi.org'); print('reached')"


@pytest.mark.skipif(not _runtime_ready(), reason="no usable container runtime")
async def test_no_egress_by_default():
    sandbox = ContainerSandbox()
    result = await sandbox.run(
        SandboxSpec(command=["python", "-c", _DNS_PROBE], timeout_s=60)
    )
    assert not result.ok  # no route, no DNS — the lookup raises and exits non-zero


@pytest.mark.skipif(not _runtime_ready(), reason="no usable container runtime")
async def test_egress_when_requested():
    sandbox = ContainerSandbox()
    result = await sandbox.run(
        SandboxSpec(command=["python", "-c", _DNS_PROBE], network=True, timeout_s=60)
    )
    assert result.ok
    assert "reached" in result.stdout
