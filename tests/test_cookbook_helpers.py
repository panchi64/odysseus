import sys

import pytest
from fastapi import HTTPException

from routes.cookbook_helpers import _safe_env_prefix, _validate_gpus, _validate_ssh_port
from routes.cookbook_runner import pip_install, server_interpreter


def test_safe_env_prefix_accepts_quoted_venv_path():
    assert (
        _safe_env_prefix("source '~/vllm-env/bin/activate'")
        == '[ -f "$HOME/vllm-env/bin/activate" ] && source "$HOME/vllm-env/bin/activate" || true'
    )


def test_safe_env_prefix_leaves_compound_conda_prefix_unchanged():
    prefix = 'eval "$(conda shell.bash hook)" && conda activate qwen35'
    assert _safe_env_prefix(prefix) == prefix


def test_safe_env_prefix_rejects_freeform_shell():
    with pytest.raises(HTTPException):
        _safe_env_prefix("echo ok; curl https://example.invalid")


def test_safe_env_prefix_accepts_powershell_activation_path():
    assert (
        _safe_env_prefix("& 'C:\\Users\\me\\venv\\Scripts\\Activate.ps1'")
        == "& 'C:\\Users\\me\\venv\\Scripts\\Activate.ps1'"
    )


def test_validate_ssh_port_rejects_shell_payload():
    with pytest.raises(HTTPException):
        _validate_ssh_port("22; touch /tmp/pwned")
    assert _validate_ssh_port("2222") == "2222"


def test_validate_gpus_accepts_indexes_only():
    assert _validate_gpus("0,1,2") == "0,1,2"
    with pytest.raises(HTTPException):
        _validate_gpus("0; rm -rf /")


def test_server_interpreter_is_running_interpreter():
    # The install↔probe invariant: local deps install into the same interpreter
    # the in-process "Installed" probe inspects.
    assert server_interpreter() == sys.executable


def test_pip_install_pins_to_target_interpreter():
    # A local dependency install must land in the given interpreter — not the
    # runner's PATH-relative python3, and never via --user (invalid in a venv).
    cmd = pip_install(["rembg[gpu]"], python=server_interpreter())
    q = sys.executable
    assert f"uv pip install --python {q!s}" in cmd or f"--python '{q}'" in cmd or q in cmd
    assert f"{q}" in cmd  # absolute interpreter present in both uv and pip branches
    assert "--user" not in cmd
    assert "$(command -v python3)" not in cmd


def test_pip_install_unpinned_keeps_path_relative_target():
    # Remote / env_prefix installs resolve python3 from PATH inside the runner.
    cmd = pip_install(["diffusers"])
    assert '$(command -v python3)' in cmd
    assert "--user" in cmd  # PEP-668 fallback retained for system pythons
