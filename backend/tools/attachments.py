"""Attachments tool — stage an attached file into the conversation's sandbox.

The agent reaches a file the operator attached to a message by its upload id (the id
rides in the attachment marker / chip). Rather than feed the file's bytes back through
the model, this **provisions** it: the original bytes are written into the conversation's
sandbox ``/work`` (the "computer" ``code_execute`` describes), so the agent can then read
and process it with code — works for any file type, not just text. It complements
``corpus.retrieve`` (semantic text search over a document) with a "give me the actual
file to compute on" path.

Thin like every tool: the upload store decrypts the bytes, the sandbox session stages
them, and this adapter translates a missing capability / bad id into something the model
can act on.
"""

from __future__ import annotations

import re

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from core.exceptions import NotFoundError
from services.sandbox import SandboxError

from .deps import RunDeps

# Where staged attachments land inside the sandbox working directory.
_STAGE_DIR = "attachments"
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _safe_name(filename: str, upload_id: str) -> str:
    """A filesystem-safe basename for the staged file. Strips any path components and
    unsafe characters; falls back to the upload id when nothing usable survives, so the
    file always lands at a predictable, escape-free path under the stage dir."""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE.sub("-", base).strip("-.")
    return cleaned or upload_id


def attachments_toolset() -> FunctionToolset[RunDeps]:
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool
    async def provision(ctx: RunContext[RunDeps], attachment_id: str) -> dict:
        """Copy a file the operator attached to this conversation into your computer's
        working directory (``/work``), so you can read and process it with
        ``code_execute``. Pass the file's upload id (shown in the attachment note /
        chip). Use this whenever you need to *work on* an attached file — any type, not
        just images: parse a CSV, analyze a spreadsheet, run code over a document, crop
        an image, and so on. It returns the ``path`` where the file was written; read it
        from there in your next ``code_execute`` call. For just searching a document's
        text, prefer ``corpus.retrieve`` with the id instead.

        The result has ``ok`` and, on success, ``path``/``filename``/``mime``/
        ``size_bytes``; on failure an ``error`` you can act on (e.g. a bad id)."""
        uploads = ctx.deps.uploads
        if uploads is None:
            return {"ok": False, "error": "Attachments are unavailable right now."}
        sessions = ctx.deps.sandbox_sessions
        if sessions is None:
            return {
                "ok": False,
                "error": "Your computer is unavailable right now: no runtime is "
                "configured, so an attachment can't be staged for processing.",
            }
        try:
            blob = await uploads.content(ctx.deps.owner_id, attachment_id)
        except NotFoundError:
            raise ModelRetry(
                f"No attachment with id {attachment_id!r}. Use an id from the "
                "attachment note for a file in this conversation."
            ) from None

        relpath = f"{_STAGE_DIR}/{_safe_name(blob.filename, attachment_id)}"
        try:
            session = await sessions.acquire(ctx.deps.sandbox_key)
            session.write_file(relpath, blob.content)
        except SandboxError as exc:
            return {"ok": False, "error": f"Could not stage the file: {exc}"}
        return {
            "ok": True,
            "path": f"/work/{relpath}",
            "filename": blob.filename,
            "mime": blob.mime,
            "size_bytes": len(blob.content),
        }

    return toolset
