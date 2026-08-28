"""Data contracts — ORM entities and Pydantic schemas.

SQLModel entities (sync, executed in a threadpool over an encrypted SQLite DB)
plus the Pydantic request/response schemas. Every record carries an owner-id
seam so multi-user isolation can be added later without a schema rewrite.

Stub — no models yet. See docs/architecture/README.md (§3, data model).
"""
