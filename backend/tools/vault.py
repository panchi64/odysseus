"""Password-vault tools (`VAULT-2`) — **reserved stub**, filled in by the vault/backup
track (T4).

See ``tools/mail.py`` for why the category is registered before it exists.

The agent reading the operator's secrets manager is an explicitly sensitive action, so
every tool here carries ``requires_approval=True`` — the static marking, as in
``tools/code.py``'s ``run_host_command``.
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset

from .deps import RunDeps


def vault_toolset() -> FunctionToolset[RunDeps]:
    """The vault category — empty until T4 lands."""
    toolset: FunctionToolset[RunDeps] = FunctionToolset()
    return toolset
