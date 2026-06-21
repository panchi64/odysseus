"""Chat attachments — the active-turn hand-off and the persisted reference.

A file the operator attaches to a message reaches the model two ways, split by
durability:

- **For the turn it's attached** it's handed over *directly* (:func:`resolve_attachments`):
  the real image for a vision-capable model — so it can actually see it, not just its OCR
  text — and the extracted text otherwise. The operator just gave it to the agent, so it's
  almost certainly relevant to this reply.
- **Everywhere after** it must *not* be re-fed on every run, so the conversation store strips
  this content back to the compact ``marker`` when it persists the turn (the marker is built
  here and handed to ``ConversationStore.record``). Later turns see only that the file exists
  (and its corpus source id) and pull it from the knowledge corpus on demand — it's enrolled
  there at upload time — and other chats reach it only through the corpus tool. That is what
  keeps history lean: available to reference, never info-dumped into context.

Shared by the chat engine now; research/agent orchestrators can adopt it unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai import BinaryContent

from core.exceptions import NotFoundError
from core.untrusted import wrap_untrusted
from models.upload import UploadStatus
from services.uploads import UploadStore

# Only true images get handed to a vision model as pixels; documents (PDFs, etc.) go in as
# their extracted text, which the upload pipeline already produces at higher fidelity than
# a raw-bytes pass would — and which a non-vision model can read too.
_IMAGE_PREFIX = "image/"


@dataclass(frozen=True)
class ResolvedAttachments:
    """The faces of a turn's attachments: ``content`` is appended to the live user prompt;
    ``marker`` is what replaces it in the persisted/replayed history; ``ids`` are the
    uploads that actually resolved (foreign/deleted ids are dropped), so only real
    attachments get stamped as chips."""

    content: list[Any]  # UserContent items (BinaryContent / wrapped text)
    marker: str
    ids: list[str]


async def resolve_attachments(
    uploads: UploadStore, owner_id: str, ids: list[str], *, vision: bool
) -> ResolvedAttachments:
    """Resolve attached upload ids into the content to hand the model for this turn.

    An image goes in as ``BinaryContent`` when the model can see (``vision``); anything
    else — and images for a text-only model — goes in as its extracted text, wrapped
    untrusted (file content is data, never instructions). A file still being extracted
    contributes a short placeholder; the corpus backfills it for later turns. Unknown or
    foreign ids are skipped."""
    content: list[Any] = []
    refs: list[str] = []
    resolved_ids: list[str] = []
    for upload_id in ids:
        try:
            view = await uploads.get(owner_id, upload_id)
        except NotFoundError:
            continue  # deleted or not the operator's — silently drop
        resolved_ids.append(upload_id)
        refs.append(f"{view.filename} (id: {upload_id})")
        if vision and view.mime.startswith(_IMAGE_PREFIX):
            blob = await uploads.content(owner_id, upload_id)
            content.append(BinaryContent(data=blob.content, media_type=view.mime))
        elif view.status == UploadStatus.DONE and view.extracted_text:
            content.append(wrap_untrusted(view.extracted_text, source=view.filename))
        else:
            content.append(
                wrap_untrusted(
                    f"[{view.filename} is still being processed — its text isn't available yet.]",
                    source=view.filename,
                )
            )
    return ResolvedAttachments(content=content, marker=_marker(refs), ids=resolved_ids)


def _marker(refs: list[str]) -> str:
    """The compact line that stands in for attachment content in persisted history — names
    the files and their source ids so the agent can pull them from the corpus when relevant."""
    if not refs:
        return ""
    listed = "; ".join(refs)
    return (
        f"[Attached file(s): {listed}. They're in the knowledge base — "
        "call the corpus.retrieve tool with a source id to read one when relevant.]"
    )
