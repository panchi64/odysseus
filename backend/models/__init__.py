"""Data contracts — ORM entities and Pydantic schemas.

SQLModel entities (sync, executed in a threadpool over an encrypted SQLite DB —
D12) plus the Pydantic request/response schemas. Every record carries an owner
seam (XC-SEC-6 / D14).

Stub — no models yet. See docs/architecture/README.md (§3, data model).
"""
