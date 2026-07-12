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
from pathlib import PurePosixPath

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from core.exceptions import NotFoundError
from services.sandbox import SandboxError

from .deps import RunDeps

# Where staged attachments land inside the sandbox working directory.
_STAGE_DIR = "attachments"
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
# Hard bound on the collision-suffix search below — sized generously above any
# realistic same-named-attachment count so a bug can't spin this forever.
_MAX_SUFFIX_ATTEMPTS = 1000


def _safe_name(filename: str, upload_id: str) -> str:
    """A filesystem-safe basename for the staged file. Strips any path components and
    unsafe characters; falls back to the upload id when nothing usable survives, so the
    file always lands at a predictable, escape-free path under the stage dir."""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE.sub("-", base).strip("-.")
    return cleaned or upload_id


def _suffixed(relpath: str, n: int) -> str:
    """``relpath`` with a ``-{n}`` suffix inserted before its extension, for the next
    collision-safe candidate name (``attachments/data.csv`` → ``attachments/data-2.csv``)."""
    path = PurePosixPath(relpath)
    return str(path.with_name(f"{path.stem}-{n}{path.suffix}"))


def _stage_unique(session, relpath: str, content: bytes) -> tuple[str, bool]:
    """Write ``content`` at ``relpath``, or the next available ``-2``/``-3``… suffixed
    name when that path is already taken by *different* bytes — two attachments sharing
    a sanitized basename (e.g. two files both named ``invoice.pdf``). The same bytes
    already at that path means the same attachment is simply being re-provisioned, so
    it is staged in place rather than renamed — re-provisioning stays idempotent.

    Returns ``(staged_relpath, renamed)``."""
    candidate = relpath
    for n in range(2, _MAX_SUFFIX_ATTEMPTS + 2):
        try:
            existing = session.read_file(candidate)
        except SandboxError:
            break  # nothing at this path — safe to use
        if existing == content:
            break  # the same file, already staged — reuse the same path
        candidate = _suffixed(relpath, n)
    # If every suffix up to _MAX_SUFFIX_ATTEMPTS is genuinely taken (astronomically
    # unlikely), the loop exits without re-checking this final candidate — it is
    # written to unverified rather than exhaustively proven free.
    session.write_file(candidate, content)
    return candidate, candidate != relpath


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
        from there in your next ``code_execute`` call — always use this returned path
        verbatim, not one you construct from the filename: when another attachment in
        this conversation already staged a file under the same name, this one is staged
        under a disambiguated name instead (the result says so). For just searching a
        document's text, prefer ``corpus.retrieve`` with the id instead.

        The result has ``ok`` and, on success, ``path``/``filename``/``mime``/
        ``size_bytes`` (plus ``renamed``/``note`` when the name was disambiguated); on
        failure an ``error`` you can act on (e.g. a bad id)."""
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
            staged_relpath, renamed = _stage_unique(session, relpath, blob.content)
        except SandboxError as exc:
            return {"ok": False, "error": f"Could not stage the file: {exc}"}
        result = {
            "ok": True,
            "path": f"/work/{staged_relpath}",
            "filename": blob.filename,
            "mime": blob.mime,
            "size_bytes": len(blob.content),
        }
        if renamed:
            result["renamed"] = True
            result["note"] = (
                f"Another attachment already used this name — staged as "
                f"{PurePosixPath(staged_relpath).name!r} instead. Use the returned "
                "path verbatim, not the original filename."
            )
        return result

    return toolset
