"""The scope catalog for inbound API tokens (`AUTH-4`).

A scope is a **named group of API surfaces**, not a permission bit: the operator issuing a
token picks the capabilities it may reach ("chat", "knowledge"), and the gate resolves the
request path back to the scope that owns it. Path prefixes are the grain because the HTTP
surface *is* the capability boundary here — each router owns exactly one feature — so the
mapping needs no per-route annotation and can't silently drift as routes are added within a
surface.

Two rules make it safe:

* **Longest prefix wins.** ``/models/serving`` resolves to the ``serving`` scope, not the
  broader ``models`` one, so bringing model servers up and down is grantable on its own.
* **Deny by default.** A path no scope claims is unreachable with a token, whatever scopes
  it carries. That is deliberate for the surfaces left out below — ``/auth``, ``/setup``,
  ``/tokens``, ``/credentials``, ``/vault``, ``/backup``, ``/shell`` — so a token can never
  mint another token, read the operator's secrets, or reach the host. Widening the reach of
  tokens is an edit here, an explicit act, rather than a side effect of adding a router.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApiScope:
    """One grantable capability group, and the API surfaces it covers."""

    id: str
    label: str
    description: str
    prefixes: tuple[str, ...]


API_SCOPES: tuple[ApiScope, ...] = (
    ApiScope(
        "chat",
        "Chat",
        "Start conversations, stream runs, and read the View.",
        ("/chat", "/conversations", "/runs", "/views"),
    ),
    ApiScope(
        "memory",
        "Memory",
        "Read and write the assistant's long-term memory.",
        ("/memory",),
    ),
    ApiScope(
        "knowledge",
        "Knowledge",
        "Documents, uploads, images, skills, and the retrieval corpus.",
        ("/documents", "/uploads", "/gallery", "/corpus", "/skills"),
    ),
    ApiScope(
        "research",
        "Research",
        "Run deep research and read its reports.",
        ("/research",),
    ),
    ApiScope(
        "search",
        "Search",
        "Query the web through the managed search provider.",
        ("/search",),
    ),
    ApiScope(
        "tasks",
        "Tasks & notifications",
        "Scheduled tasks, their run history, and the notification stream.",
        ("/tasks", "/notifications"),
    ),
    ApiScope(
        "models",
        "Models",
        "Read the model registry, roles, and the Cookbook catalog.",
        ("/models",),
    ),
    ApiScope(
        "serving",
        "Model serving",
        "Start and stop local model servers — powerful; grant deliberately.",
        ("/models/serving",),
    ),
    ApiScope(
        "status",
        "Status",
        "Read-only system status and the home overview.",
        ("/overview", "/offline"),
    ),
)

SCOPE_IDS: frozenset[str] = frozenset(scope.id for scope in API_SCOPES)

# Longest prefix first, so the first match is the most specific one.
_BY_SPECIFICITY: tuple[tuple[str, str], ...] = tuple(
    sorted(
        ((prefix, scope.id) for scope in API_SCOPES for prefix in scope.prefixes),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
)


def scope_for_path(path: str) -> str | None:
    """The scope a request path belongs to, or ``None`` when no scope claims it.

    ``None`` means *unreachable with a token* — the deny-by-default half of the rule."""
    for prefix, scope_id in _BY_SPECIFICITY:
        if path == prefix or path.startswith(prefix + "/"):
            return scope_id
    return None


def unknown_scopes(scopes: list[str]) -> list[str]:
    """The requested scope ids that aren't in the catalog — an issue-time validation."""
    return [s for s in scopes if s not in SCOPE_IDS]
