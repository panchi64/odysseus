"""The scope catalog for inbound API tokens (`AUTH-4`).

A scope is a **named group of API surfaces**, not a permission bit: the operator issuing a
token picks the capabilities it may reach ("chat", "knowledge"), and the gate resolves the
request path back to the scope that owns it. Path prefixes are the grain because the HTTP
surface *is* the capability boundary here — each router owns exactly one feature — so the
mapping needs no per-route annotation and can't silently drift as routes are added within a
surface.

Core owns the **vocabulary** (`SCOPE_DEFS` — the operator-facing groups) and the
**machinery** (`ScopeTable`); the *claims* mapping prefixes into a scope arrive at app
assembly — `CORE_CLAIMS` for the surfaces core itself wires, plus each feature manifest's
own claims — so core never has to know which features exist.

Two rules make it safe:

* **Longest prefix wins.** ``/models/serving`` resolves to the ``serving`` scope, not the
  broader ``models`` one, so bringing model servers up and down is grantable on its own.
* **Deny by default.** A path no claim covers is unreachable with a token, whatever scopes
  it carries. That is deliberate for the surfaces that claim nothing — ``/auth``,
  ``/setup``, ``/tokens``, ``/credentials``, ``/vault``, ``/backup``, ``/shell``, mail,
  calendar, external tools — so a token can never mint another token, read the operator's
  secrets, or reach the host. Widening a token's reach is an explicit claim, an act,
  rather than a side effect of adding a router.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ScopeDef:
    """One grantable capability group, as the operator sees it."""

    id: str
    label: str
    description: str


@dataclass(frozen=True)
class ScopeClaim:
    """Path prefixes claimed into a scope — contributed by core assembly and by
    feature manifests. The scope id must name a `SCOPE_DEFS` entry."""

    scope_id: str
    prefixes: tuple[str, ...]


@dataclass(frozen=True)
class ApiScope:
    """A scope with its merged prefixes — the shape the token-issuing surface lists."""

    id: str
    label: str
    description: str
    prefixes: tuple[str, ...]


SCOPE_DEFS: tuple[ScopeDef, ...] = (
    ScopeDef("chat", "Chat", "Start conversations, stream runs, and read the View."),
    ScopeDef("memory", "Memory", "Read and write the assistant's long-term memory."),
    ScopeDef(
        "knowledge",
        "Knowledge",
        "Documents, uploads, images, skills, and the retrieval corpus.",
    ),
    ScopeDef("research", "Research", "Run deep research and read its reports."),
    ScopeDef("search", "Search", "Query the web through the managed search provider."),
    ScopeDef(
        "tasks",
        "Tasks & notifications",
        "Scheduled tasks, their run history, and the notification stream.",
    ),
    ScopeDef("models", "Models", "Read the model registry, roles, and the Cookbook catalog."),
    ScopeDef(
        "serving",
        "Model serving",
        "Start and stop local model servers — powerful; grant deliberately.",
    ),
    ScopeDef("status", "Status", "Read-only system status and the home overview."),
)

# The surfaces the core assembly itself wires (see `app.py`); every feature surface
# claims through its own manifest.
CORE_CLAIMS: tuple[ScopeClaim, ...] = (
    ScopeClaim("chat", ("/chat", "/conversations", "/runs")),
    ScopeClaim("models", ("/models",)),
    ScopeClaim("status", ("/overview",)),
)

_DEFS_BY_ID = {d.id: d for d in SCOPE_DEFS}


class ScopeTable:
    """The assembled path→scope mapping for one app instance."""

    def __init__(self, claims: Iterable[ScopeClaim]) -> None:
        merged: dict[str, list[str]] = {}
        for claim in claims:
            if claim.scope_id not in _DEFS_BY_ID:
                raise ValueError(f"scope claim names unknown scope id {claim.scope_id!r}")
            merged.setdefault(claim.scope_id, []).extend(claim.prefixes)
        # Catalog order follows SCOPE_DEFS; a scope nothing claims is simply absent —
        # never offered on a token it could not put to use.
        self.scopes: tuple[ApiScope, ...] = tuple(
            ApiScope(d.id, d.label, d.description, tuple(merged[d.id]))
            for d in SCOPE_DEFS
            if d.id in merged
        )
        self.scope_ids: frozenset[str] = frozenset(merged)
        # Longest prefix first, so the first match is the most specific one.
        self._by_specificity: tuple[tuple[str, str], ...] = tuple(
            sorted(
                ((prefix, scope.id) for scope in self.scopes for prefix in scope.prefixes),
                key=lambda pair: len(pair[0]),
                reverse=True,
            )
        )

    def scope_for_path(self, path: str) -> str | None:
        """The scope a request path belongs to, or ``None`` when no claim covers it.

        ``None`` means *unreachable with a token* — the deny-by-default half of the rule."""
        for prefix, scope_id in self._by_specificity:
            if path == prefix or path.startswith(prefix + "/"):
                return scope_id
        return None

    def unknown_scopes(self, scopes: list[str]) -> list[str]:
        """The requested scope ids that aren't in the table — an issue-time validation."""
        return [s for s in scopes if s not in self.scope_ids]
