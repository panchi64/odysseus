"""Chat attachments — the active-turn hand-off and the retained reference.

A file the operator attaches to a message reaches the model two ways, split by what the
*live turn* needs versus what *replayed history* should carry:

- **For the turn it's attached** it's handed over in full (:attr:`ResolvedAttachments.content`):
  the real image for a vision model (so it can see it, not just its OCR text) and the
  whole extracted text otherwise. The operator just gave it to the agent, so the attach
  turn uses everything.
- **In replayed history** the content is **retained inline up to a token cap**
  (:attr:`ResolvedAttachments.persisted`): an image always stays (its cost is bounded and
  there is no way to re-see one on demand), and a non-image file's text stays whole while
  it is under the cap. A larger document is **cut off at the cap with a pointer appended**
  telling the model to reach the full file through the ``attachments_provision`` tool
  (stage the bytes into the sandbox) or ``corpus.retrieve`` (search its text) by id. A
  compact marker listing every attachment's id closes the persisted block, so the model
  can provision *any* attachment — even a fully-inline one — when it needs to run code on it.

Keeping the durable history capped is what stops a large file from growing context without
bound while still leaving it one tool call away. Shared by the chat engine now;
research/agent orchestrators can adopt it unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai import BinaryContent

from core.exceptions import NotFoundError
from core.text import tokens_to_chars, truncate_on_boundary
from core.untrusted import wrap_untrusted
from models.upload import UploadStatus
from services.uploads import UploadStore

# Only true images get handed to a vision model as pixels; documents (PDFs, etc.) go in as
# their extracted text, which the upload pipeline already produces at higher fidelity than
# a raw-bytes pass would — and which a non-vision model can read too.
_IMAGE_PREFIX = "image/"


@dataclass(frozen=True)
class ResolvedAttachments:
    """The two faces of a turn's attachments. ``content`` is the full set appended to the
    live user prompt (what the attach turn sees); ``persisted`` is the capped set that
    replaces it in durable/replayed history (images + under-cap text inline, larger text
    cut to a pointer, a closing id marker). ``ids`` are the uploads that actually resolved
    (foreign/deleted ids dropped), so only real attachments get stamped as chips."""

    content: list[Any]  # live-turn UserContent (full)
    persisted: list[Any]  # durable UserContent (capped + pointers + marker)
    ids: list[str]


async def resolve_attachments(
    uploads: UploadStore,
    owner_id: str,
    ids: list[str],
    *,
    vision: bool,
    inline_max_tokens: int,
) -> ResolvedAttachments:
    """Resolve attached upload ids into the live and durable content for this turn.

    An image goes in as ``BinaryContent`` when the model can see (``vision``); anything
    else — and images for a text-only model — goes in as its extracted text, wrapped
    untrusted (file content is data, never instructions). ``content`` carries the full
    content for the live turn; ``persisted`` carries it capped to ``inline_max_tokens``
    for replayed history (a longer document is truncated and a tool pointer appended).
    A file still being extracted contributes a short placeholder. Unknown or foreign ids
    are skipped."""
    content: list[Any] = []
    persisted: list[Any] = []
    refs: list[str] = []
    resolved_ids: list[str] = []
    max_chars = tokens_to_chars(inline_max_tokens)
    for upload_id in ids:
        try:
            view = await uploads.get(owner_id, upload_id)
        except NotFoundError:
            continue  # deleted or not the operator's — silently drop
        resolved_ids.append(upload_id)
        refs.append(f"{view.filename} (id: {upload_id})")
        if vision and view.mime.startswith(_IMAGE_PREFIX):
            blob = await uploads.content(owner_id, upload_id)
            binary = BinaryContent(data=blob.content, media_type=view.mime)
            content.append(binary)
            persisted.append(binary)  # an image is always retained inline
        elif view.status == UploadStatus.DONE and view.extracted_text:
            text = view.extracted_text
            full = wrap_untrusted(text, source=view.filename)
            content.append(full)
            if len(text) <= max_chars:
                persisted.append(full)  # same wrapped block, not re-wrapped
            else:
                truncated = truncate_on_boundary(text, max_chars)
                if truncated:
                    persisted.append(wrap_untrusted(truncated, source=view.filename))
                persisted.append(_truncation_note(upload_id, view.filename, inline_max_tokens))
        else:
            placeholder = wrap_untrusted(
                f"[{view.filename} is still being processed — its text isn't available yet.]",
                source=view.filename,
            )
            content.append(placeholder)
            persisted.append(placeholder)
    marker = _marker(refs)
    if marker:
        persisted.append(marker)
    return ResolvedAttachments(content=content, persisted=persisted, ids=resolved_ids)


def _truncation_note(upload_id: str, filename: str, cap_tokens: int) -> str:
    """The trusted pointer appended after a cut-off file's content — an instruction to the
    model (kept *outside* the untrusted wrapper) to reach the full file via the tools."""
    return (
        f"[The file {filename!r} (id: {upload_id}) was cut off at the {cap_tokens}-token "
        "inline limit. To read the full file, load it into your computer with the "
        "attachments_provision tool, or search its text with corpus.retrieve — using the id above.]"
    )


def _marker(refs: list[str]) -> str:
    """The compact line closing the persisted attachment block — names the files and their
    ids and points at the tools, so the agent can load any of them into the sandbox (or
    search a document's text) on a later turn even when the content is retained inline."""
    if not refs:
        return ""
    listed = "; ".join(refs)
    return (
        f"[Attached file(s): {listed}. To work with a file's bytes (run code on it), load it "
        "into your computer's /work with the attachments_provision tool; to search a "
        "document's text, use corpus.retrieve with its id.]"
    )
