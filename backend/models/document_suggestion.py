"""Document suggestion schema (`DOC-3`) — **reserved stub**, filled in by the doc assist
track (T5).

See ``models/mail.py`` for why the module is imported before it declares anything.

For the track that fills this in: a suggestion is a *proposed* change that has not been
applied, which is what separates it from ``DocumentVersion`` (an append-only record of
changes that already happened). Only accepting one mints a version.
"""

from __future__ import annotations
