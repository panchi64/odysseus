"""The embedding reindex coordinator: heal counts, model passthrough, degrade paths."""

from __future__ import annotations

from dataclasses import dataclass

from core.exceptions import DegradedCapabilityError, NotFoundError
from services.reindex import EmbeddingReindexer

OWNER = "operator"


@dataclass
class _Spec:
    model: str


class _Registry:
    def __init__(self, *, spec: _Spec | None = None, exc: Exception | None = None) -> None:
        self._spec = spec
        self._exc = exc

    async def resolve_embedding_spec(self, owner_id: str) -> _Spec:
        if self._exc is not None:
            raise self._exc
        assert self._spec is not None
        return self._spec


class _Memory:
    def __init__(self, n: int = 0) -> None:
        self._n = n
        self.seen_model: str | None = None

    async def reembed(self, owner_id: str, *, current_model=None, batch_size: int = 64) -> int:
        self.seen_model = current_model
        return self._n


class _Convos:
    def __init__(self, n: int = 0) -> None:
        self._n = n
        self.seen_model: str | None = None

    async def reindex_embeddings(
        self, owner_id: str, *, current_model=None, batch_size: int = 64
    ) -> int:
        self.seen_model = current_model
        return self._n


async def test_reindex_reports_counts_and_passes_current_model():
    mem, conv = _Memory(3), _Convos(5)
    reindexer = EmbeddingReindexer(_Registry(spec=_Spec("embed-m")), mem, conv)
    await reindexer._run(OWNER)

    status = reindexer.status()
    assert status.state == "done"
    assert status.memories == 3 and status.messages == 5
    # Both stores are healed against the currently-resolved model (EMB-2).
    assert mem.seen_model == "embed-m" and conv.seen_model == "embed-m"


async def test_reindex_degrades_when_no_embedder():
    reindexer = EmbeddingReindexer(
        _Registry(exc=DegradedCapabilityError("unset")), _Memory(), _Convos()
    )
    await reindexer._run(OWNER)
    assert reindexer.status().state == "degraded"


async def test_reindex_degrades_when_endpoint_deleted():
    # A NotFoundError (the endpoint vanished mid-run) must reach a terminal state,
    # not leave the status stuck at 'running' so the UI spins forever.
    reindexer = EmbeddingReindexer(
        _Registry(exc=NotFoundError("gone")), _Memory(), _Convos()
    )
    await reindexer._run(OWNER)
    assert reindexer.status().state == "degraded"
