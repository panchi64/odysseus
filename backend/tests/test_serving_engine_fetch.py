"""llama.cpp prebuilt selection — which release asset a host fetches, and unpacking it.

The asset list is a verbatim slice of a real ggml-org release so the matching is tested
against the names actually published (tarballs on Linux/macOS, zips on Windows, and the
decoy variants that a substring match would trip over). No network: the release payload
is a fixture and extraction runs against a tarball built in a tmp dir.
"""

from __future__ import annotations

import stat
import tarfile
from pathlib import Path

from services.serving.adapters import llamacpp
from services.serving.adapters.llamacpp import _extract_server, _host_variants, _pick_asset

# The asset names published for release b10472, unchanged.
_ASSET_NAMES = [
    "cudart-llama-bin-win-cuda-12.4-x64.zip",
    "llama-b10472-bin-macos-arm64.tar.gz",
    "llama-b10472-bin-macos-x64.tar.gz",
    "llama-b10472-bin-ubuntu-arm64.tar.gz",
    "llama-b10472-bin-ubuntu-openvino-2026.2.1-x64.tar.gz",
    "llama-b10472-bin-ubuntu-s390x.tar.gz",
    "llama-b10472-bin-ubuntu-sycl-fp16-x64.tar.gz",
    "llama-b10472-bin-ubuntu-sycl-fp32-x64.tar.gz",
    "llama-b10472-bin-ubuntu-vulkan-arm64.tar.gz",
    "llama-b10472-bin-ubuntu-vulkan-x64.tar.gz",
    "llama-b10472-bin-ubuntu-x64.tar.gz",
    "llama-b10472-bin-win-cpu-x64.zip",
    "llama-b10472-bin-win-cuda-12.4-x64.zip",
    "llama-b10472-bin-win-vulkan-x64.zip",
]
_ASSETS = [
    {"name": n, "browser_download_url": f"https://example.invalid/{n}"} for n in _ASSET_NAMES
]


def _host(monkeypatch, system: str, machine: str, *, vulkan: bool) -> None:
    monkeypatch.setattr(llamacpp.platform, "system", lambda: system)
    monkeypatch.setattr(llamacpp.platform, "machine", lambda: machine)
    monkeypatch.setattr(llamacpp, "find_library", lambda name: "libvulkan.so.1" if vulkan else None)


# --- variant selection ------------------------------------------------------


def test_linux_x64_with_a_vulkan_loader_prefers_the_gpu_build(monkeypatch):
    _host(monkeypatch, "Linux", "x86_64", vulkan=True)
    assert _host_variants() == ("ubuntu-vulkan-x64", "ubuntu-x64")
    asset = _pick_asset(_ASSETS, _host_variants())
    assert asset["name"] == "llama-b10472-bin-ubuntu-vulkan-x64.tar.gz"


def test_linux_x64_without_a_vulkan_loader_falls_back_to_cpu(monkeypatch):
    # The Vulkan binary links against libvulkan; without it, it would not start at all.
    _host(monkeypatch, "Linux", "x86_64", vulkan=False)
    assert _host_variants() == ("ubuntu-x64",)
    asset = _pick_asset(_ASSETS, _host_variants())
    assert asset["name"] == "llama-b10472-bin-ubuntu-x64.tar.gz"


def test_apple_silicon_picks_the_metal_carrying_macos_build(monkeypatch):
    _host(monkeypatch, "Darwin", "arm64", vulkan=False)
    asset = _pick_asset(_ASSETS, _host_variants())
    assert asset["name"] == "llama-b10472-bin-macos-arm64.tar.gz"


def test_linux_arm64_reported_either_way_resolves(monkeypatch):
    for machine in ("aarch64", "arm64"):
        _host(monkeypatch, "Linux", machine, vulkan=True)
        asset = _pick_asset(_ASSETS, _host_variants())
        assert asset["name"] == "llama-b10472-bin-ubuntu-vulkan-arm64.tar.gz"


def test_variant_matching_is_a_suffix_not_a_substring(monkeypatch):
    # "ubuntu-x64" occurs inside "ubuntu-openvino-2026.2.1-x64" and the sycl names; a
    # substring match would hand a CPU host an OpenVINO or SYCL build.
    _host(monkeypatch, "Linux", "x86_64", vulkan=False)
    asset = _pick_asset(_ASSETS, _host_variants())
    assert "openvino" not in asset["name"] and "sycl" not in asset["name"]


def test_unsupported_arch_reports_no_variants(monkeypatch):
    _host(monkeypatch, "Linux", "s390x", vulkan=False)
    assert _host_variants() == ()
    assert _pick_asset(_ASSETS, _host_variants()) is None


def test_pick_asset_skips_entries_without_a_download_url(monkeypatch):
    _host(monkeypatch, "Linux", "x86_64", vulkan=False)
    assets = [{"name": "llama-b10472-bin-ubuntu-x64.tar.gz"}]  # no browser_download_url
    assert _pick_asset(assets, _host_variants()) is None


# --- extraction -------------------------------------------------------------


def _tarball(tmp_path: Path) -> Path:
    payload = tmp_path / "build" / "bin"
    payload.mkdir(parents=True)
    (payload / "llama-server").write_text("#!/bin/sh\n")
    (payload / "libggml.so").write_text("")
    archive = tmp_path / "llama-b10472-bin-ubuntu-x64.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(payload / "llama-server", arcname="build/bin/llama-server")
        tar.add(payload / "libggml.so", arcname="build/bin/libggml.so")
    return archive


def test_tarball_extraction_yields_an_executable_server(tmp_path):
    dest = tmp_path / "engine"
    dest.mkdir()
    binary = _extract_server(_tarball(tmp_path), dest)
    assert binary is not None and binary.name == "llama-server"
    assert binary.stat().st_mode & stat.S_IXUSR
    # The archive is cleaned up once unpacked.
    assert not (tmp_path / "llama-b10472-bin-ubuntu-x64.tar.gz").exists()


def test_extraction_returns_none_when_the_archive_has_no_server(tmp_path):
    archive = tmp_path / "empty.tar.gz"
    stray = tmp_path / "README.md"
    stray.write_text("x")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(stray, arcname="README.md")
    dest = tmp_path / "engine"
    dest.mkdir()
    assert _extract_server(archive, dest) is None
