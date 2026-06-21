"""Chat file attachments + the retroactive knowledge-base exclude toggle.

Covers the two halves of the feature: a file is handed to the model *for the turn it's
attached* (pixels for a vision model, extracted text otherwise) but stripped to a marker
on persist — so it's available to reference, never re-fed every run — and an enrolled
upload can be scoped out of the corpus retroactively, dropping it from every retrieve.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from pydantic_ai import BinaryContent
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from sqlmodel import Session, select

from agent import build_chat_orchestrator
from agent.attachments import resolve_attachments
from core.db import in_session, init_db, make_engine
from core.vault import Vault
from models.corpus import CorpusChunk
from models.upload import Upload, UploadStatus
from runs import RunRegistry, RunStatus
from services.conversations import ConversationStore, with_attachment_marker
from services.corpus.chunk_store import CorpusChunkStore
from services.corpus.index import CorpusIndex
from services.corpus.uploads import UploadsAdapter
from services.registry import ModelRegistry
from services.upload_extraction import BasicExtractor
from services.uploads import UploadStore

from ._helpers import client_app, collect_sse_events, patch_model_resolution
from .test_memory import FakeEmbedder
from .test_uploads_extraction import NoVisionOCR

OWNER = "operator"


# --- fixtures ---------------------------------------------------------------


async def _uploads_store():
    """An UploadStore + its corpus adapter over a throwaway in-memory DB. Workers are NOT
    started here — tests that index/drain start (and stop) them explicitly, so no drainer
    task is left pending at teardown. Resolve-only tests never need a worker."""
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(Path(tempfile.mkdtemp()) / "keyfile.json")
    await vault.setup("pw")
    chunk_store = CorpusChunkStore(engine, vault, FakeEmbedder())
    adapter = UploadsAdapter(engine, chunk_store, vault.unlocked_event)
    store = UploadStore(engine, vault, adapter, BasicExtractor(NoVisionOCR()))
    return engine, vault, chunk_store, adapter, store


async def _insert_upload(
    engine,
    vault,
    *,
    mime: str,
    text: str | None = "the operator's secret zebra dossier",
    status: str = UploadStatus.DONE,
    content: bytes = b"raw-bytes",
) -> str:
    """Insert an Upload row directly, for precise control over mime/status/text."""

    def work(session: Session) -> str:
        upload = Upload(
            owner_id=OWNER,
            filename_enc=vault.encrypt_str("dossier"),
            mime=mime,
            size_bytes=len(content),
            sha256=hashlib.sha256(content + mime.encode()).hexdigest(),
            blob_enc=vault.encrypt_bytes(content),
            status=status,
            extracted_text_enc=vault.encrypt_str(text) if text else None,
            has_text=bool(text),
        )
        session.add(upload)
        session.flush()
        return upload.id

    return await in_session(engine, work)


# --- resolve_attachments: the active-turn hand-off --------------------------


async def test_vision_model_gets_the_image_as_pixels():
    engine, _vault, _chunks, _adapter, store = await _uploads_store()
    uid = await _insert_upload(engine, store._vault, mime="image/png")

    resolved = await resolve_attachments(store, OWNER, [uid], vision=True)

    assert any(isinstance(part, BinaryContent) for part in resolved.content)
    assert "dossier" in resolved.marker and uid in resolved.marker


async def test_text_only_model_gets_extracted_text_wrapped_untrusted():
    engine, _vault, _chunks, _adapter, store = await _uploads_store()
    uid = await _insert_upload(engine, store._vault, mime="image/png")

    resolved = await resolve_attachments(store, OWNER, [uid], vision=False)

    # No pixels for a text-only model — the file's extracted text, wrapped as data.
    assert not any(isinstance(part, BinaryContent) for part in resolved.content)
    body = "".join(p for p in resolved.content if isinstance(p, str))
    assert "zebra dossier" in body
    assert "untrusted" in body.lower()  # wrap_untrusted sentinel/instruction present


async def test_still_processing_attachment_yields_a_placeholder():
    engine, _vault, _chunks, _adapter, store = await _uploads_store()
    uid = await _insert_upload(
        engine, store._vault, mime="application/pdf", text=None, status=UploadStatus.EXTRACTING
    )

    resolved = await resolve_attachments(store, OWNER, [uid], vision=False)

    body = "".join(p for p in resolved.content if isinstance(p, str))
    assert "still being processed" in body


async def test_unknown_attachment_id_is_skipped():
    engine, _vault, _chunks, _adapter, store = await _uploads_store()
    resolved = await resolve_attachments(store, OWNER, ["nope"], vision=True)
    assert resolved.content == [] and resolved.marker == ""


# --- with_attachment_marker: the persisted reference ------------------------


def test_marker_replaces_content_keeping_the_prompt():
    request = ModelRequest(
        parts=[
            UserPromptPart(
                content=["summarize this", BinaryContent(data=b"x", media_type="image/png")]
            )
        ]
    )
    with_attachment_marker(request, "[Attached file(s): a.png (id: up1).]")

    part = request.parts[0]
    assert isinstance(part.content, str)  # collapsed to text — no binary survives
    assert part.content.startswith("summarize this")
    assert "Attached file(s)" in part.content


# --- the engine: inject once, persist a marker ------------------------------


async def _conv_store():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(Path(tempfile.mkdtemp()) / "keyfile.json")
    await vault.setup("pw")
    return ConversationStore(engine, vault, FakeEmbedder())


async def test_attachment_reaches_model_but_history_keeps_only_the_marker():
    # The file is handed to the model for this turn (pixels, vision=True), but the
    # persisted/replayed history carries only the marker — the no-info-dump guarantee.
    up_engine, _v, _c, _a, uploads = await _uploads_store()
    uid = await _insert_upload(up_engine, uploads._vault, mime="image/png")

    conv = await _conv_store()
    await conv.start()
    cid = await conv.create_conversation(OWNER)

    # Snapshot what the model actually received *at call time* — the message object is
    # mutated in place by the marker-strip afterward, so we can't read it back later.
    saw_binary: list[bool] = []

    async def capture(messages, info):
        # The engine streams the turn, so a stream_function is what FunctionModel needs.
        user = next(p for m in messages for p in m.parts if isinstance(p, UserPromptPart))
        content = user.content if isinstance(user.content, list) else [user.content]
        saw_binary.append(any(isinstance(item, BinaryContent) for item in content))
        yield "looked at it"

    orch = build_chat_orchestrator(
        "what is this?",
        model=FunctionModel(stream_function=capture),
        store=conv,
        conversation_id=cid,
        uploads=uploads,
        attachment_ids=[uid],
        vision=True,
    )
    run = RunRegistry().submit(kind="chat", owner_id=OWNER, orchestrator=orch)
    await run.wait()
    assert run.status is RunStatus.done

    # The model saw the actual image this turn …
    assert saw_binary == [True]

    # … but the persisted history carries only the marker — no binary to replay.
    history = await conv.history(cid)
    text = next(p.content for p in history[0].parts if isinstance(p, UserPromptPart))
    assert isinstance(text, str)  # collapsed to text, not a multimodal list
    assert "what is this?" in text and uid in text
    await conv.stop()


# --- the retroactive knowledge-base exclude toggle --------------------------


async def _drain_adapter(adapter):
    await adapter._worker.join()


async def test_excluded_upload_drops_from_retrieve_and_returns_on_reinclude():
    engine, _vault, chunk_store, adapter, _store = await _uploads_store()
    await adapter.start()
    try:
        adapter.index_upload(OWNER, "up-zebra", "the zebra dossier lives here")
        await _drain_adapter(adapter)
        assert await adapter.retrieve(OWNER, "zebra", None, None, {"zebra"}, limit=5)

        adapter.set_excluded(OWNER, "up-zebra", True)
        await _drain_adapter(adapter)
        assert await adapter.retrieve(OWNER, "zebra", None, None, {"zebra"}, limit=5) == []

        adapter.set_excluded(OWNER, "up-zebra", False)
        await _drain_adapter(adapter)
        assert await adapter.retrieve(OWNER, "zebra", None, None, {"zebra"}, limit=5)
    finally:
        await adapter.stop()


async def test_set_kb_excluded_flips_flag_and_restamps_chunks():
    engine, vault, chunk_store, adapter, store = await _uploads_store()
    await store.start()
    await adapter.start()
    view, _created = await store.create(OWNER, "n.txt", "text/plain", b"zebra facts abound here")
    await store._worker.join()
    await adapter._worker.join()

    await store.set_kb_excluded(OWNER, view.id, True)
    await adapter._worker.join()

    refreshed = await store.get(OWNER, view.id)
    assert refreshed.kb_excluded is True
    with Session(engine) as session:
        chunks = session.exec(select(CorpusChunk).where(CorpusChunk.source_id == view.id)).all()
    assert chunks and all(c.kb_excluded for c in chunks)
    assert await adapter.retrieve(OWNER, "zebra", None, None, {"zebra"}, limit=5) == []

    await store.set_kb_excluded(OWNER, view.id, False)
    await adapter._worker.join()
    assert await adapter.retrieve(OWNER, "zebra", None, None, {"zebra"}, limit=5)
    await store.stop()
    await adapter.stop()


async def test_targeted_source_ids_read_scopes_to_one_file_and_overrides_exclude():
    engine, vault, chunk_store, adapter, _store = await _uploads_store()
    await adapter.start()
    try:
        adapter.index_upload(OWNER, "file-a", "alpha content about otters")
        adapter.index_upload(OWNER, "file-b", "beta content about otters")
        await _drain_adapter(adapter)

        index = CorpusIndex(
            FakeEmbedder(), ModelRegistry.__new__(ModelRegistry), chunk_store, folder=None  # type: ignore[arg-type]
        )
        hits = await index.retrieve(OWNER, "otters", source_ids=["file-a"], limit=5)
        assert hits and all(h.source_id == "file-a" for h in hits)

        # Excluding scopes the file out of AMBIENT recall (no source_ids)...
        adapter.set_excluded(OWNER, "file-a", True)
        await _drain_adapter(adapter)
        assert await index.retrieve(OWNER, "otters", sources=["uploads"], limit=5) == []
        # ...but an explicit by-id fetch (a chat reading its own attachment) still gets it.
        still = await index.retrieve(OWNER, "otters", source_ids=["file-a"], limit=5)
        assert still and all(h.source_id == "file-a" for h in still)
    finally:
        await adapter.stop()


# --- routes -----------------------------------------------------------------


async def _upload_file(client, name="note.txt", body=b"hello there", mime="text/plain"):
    resp = await client.post("/uploads", files={"file": (name, body, mime)})
    assert resp.status_code in (200, 201)
    return resp.json()["id"]


async def test_chat_accepts_attachment_ids_and_turn_carries_them(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, _app):
        uid = await _upload_file(client)
        resp = await client.post(
            "/chat", json={"prompt": "look at my file", "attachment_ids": [uid]}
        )
        assert resp.status_code == 202
        body = resp.json()
        await collect_sse_events(client, body["run_id"])

        detail = await client.get(f"/conversations/{body['conversation_id']}")
        messages = detail.json()["messages"]
        user_turn = next(m for m in messages if m["role"] == "user")
        # The conversations route emits snake_case (MessageOut is a plain BaseModel,
        # unlike the camelCase upload DTOs); the frontend maps it to attachmentIds.
        assert user_turn["attachment_ids"] == [uid]


async def test_chat_rejects_unknown_attachment_id(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, _app):
        resp = await client.post("/chat", json={"prompt": "hi", "attachment_ids": ["ghost"]})
        assert resp.status_code == 404


async def test_chat_allows_empty_prompt_with_an_attachment(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, _app):
        uid = await _upload_file(client)
        resp = await client.post("/chat", json={"prompt": "", "attachment_ids": [uid]})
        assert resp.status_code == 202
        # …but still nothing to act on with neither text nor a file.
        empty = await client.post("/chat", json={"prompt": "   "})
        assert empty.status_code == 422


async def test_patch_upload_toggles_kb_excluded(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, _app):
        uid = await _upload_file(client)
        resp = await client.patch(f"/uploads/{uid}", json={"kbExcluded": True})
        assert resp.status_code == 200
        assert resp.json()["kbExcluded"] is True

        back = await client.patch(f"/uploads/{uid}", json={"kbExcluded": False})
        assert back.json()["kbExcluded"] is False
