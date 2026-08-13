"""External tool schema — MCP servers, connectors, and per-tool trust (`MCP-*`, `INTEG-*`,
`AE-3.6`) — **reserved stub**, filled in by the external tools track (T3).

See ``models/mail.py`` for why the module is imported before it declares anything.

For the track that fills this in: trust is **per tool, not per server**, so registering or
enabling a server must not blanket-trust everything it exposes. Like ``ApprovalGrant``, a
trust record is *policy rather than content* — so it stays in the clear and is indexable;
only a server's credentials need sealing.
"""

from __future__ import annotations
