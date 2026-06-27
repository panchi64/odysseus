"""Workspace history store — capture, list, browse, and diff sandbox snapshots.

The capability behind git-style View history. After a file-changing turn the
sandbox workspace's text files are captured as a **snapshot**: bytes are
content-addressed and encrypted at rest under the vault (deduped by hash across
snapshots), the manifest (path → hash) records the tree. Reads decrypt on demand
and compute diffs server-side with :mod:`difflib` — no git binary, no container.

Mirrors :mod:`services.artifacts`: owner-scoped, vault-sealed bytes, clear
metadata, all DB work through ``core.db.in_session``.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, delete
from sqlmodel import Session, select

from core.db import in_session
from core.exceptions import NotFoundError
from core.vault import Vault
from models.workspace_history import WorkspaceBlob, WorkspaceSnapshot


@dataclass(frozen=True)
class SnapshotView:
    """Snapshot metadata for listing and the capture event (no bytes)."""

    id: str
    conversation_id: str
    title: str | None
    created_at: datetime
    files_changed: int
    summary: str  # compact change tally, e.g. "+2 ~1 -0"
    stats: dict[str, int]  # added / modified / removed vs. the previous snapshot


@dataclass(frozen=True)
class FileEntry:
    """A file present in a snapshot, with its change status vs. the previous one."""

    path: str
    status: str  # "added" | "modified" | "unchanged"


@dataclass(frozen=True)
class FileDiff:
    """A changed file between two snapshots; ``diff`` is empty for binary files."""

    path: str
    status: str  # "added" | "modified" | "removed"
    diff: str


class WorkspaceHistoryStore:
    def __init__(self, engine: Engine, vault: Vault) -> None:
        self._engine = engine
        self._vault = vault

    async def capture(
        self,
        owner_id: str,
        conversation_id: str,
        *,
        run_id: str | None,
        files: dict[str, bytes],
        title: str | None = None,
    ) -> SnapshotView | None:
        """Capture the current file set as a snapshot, or ``None`` if nothing changed
        since the last one (so a turn that touched no files records no version)."""

        def work(session: Session) -> SnapshotView | None:
            manifest = {path: _sha256(data) for path, data in sorted(files.items())}
            prev = session.exec(
                select(WorkspaceSnapshot)
                .where(WorkspaceSnapshot.owner_id == owner_id)
                .where(WorkspaceSnapshot.conversation_id == conversation_id)
                .order_by(WorkspaceSnapshot.created_at.desc())  # type: ignore[attr-defined]
            ).first()
            prev_manifest: dict[str, str] = json.loads(prev.manifest_json) if prev else {}
            if manifest == prev_manifest:
                return None  # no change → no new version

            needed = set(manifest.values())
            have = set(
                session.exec(
                    select(WorkspaceBlob.sha256)
                    .where(WorkspaceBlob.owner_id == owner_id)
                    .where(WorkspaceBlob.sha256.in_(needed))  # type: ignore[attr-defined]
                ).all()
            )
            for path, sha in manifest.items():
                if sha in have:
                    continue
                have.add(sha)  # a file repeated within this snapshot is stored once
                session.add(
                    WorkspaceBlob(
                        owner_id=owner_id,
                        sha256=sha,
                        size=len(files[path]),
                        blob_enc=self._vault.encrypt_bytes(files[path]),
                    )
                )

            stats = _stats(prev_manifest, manifest)
            snapshot = WorkspaceSnapshot(
                owner_id=owner_id,
                conversation_id=conversation_id,
                run_id=run_id,
                title=title,
                manifest_json=json.dumps(manifest),
                stats_json=json.dumps(stats),
            )
            session.add(snapshot)
            session.flush()
            return _to_view(snapshot)

        return await in_session(self._engine, work)

    async def list(self, owner_id: str, conversation_id: str) -> list[SnapshotView]:
        def work(session: Session) -> list[SnapshotView]:
            rows = session.exec(
                select(WorkspaceSnapshot)
                .where(WorkspaceSnapshot.owner_id == owner_id)
                .where(WorkspaceSnapshot.conversation_id == conversation_id)
                .order_by(WorkspaceSnapshot.created_at)  # type: ignore[arg-type]
            ).all()
            return [_to_view(row) for row in rows]

        return await in_session(self._engine, work)

    async def files(self, owner_id: str, snapshot_id: str) -> list[FileEntry]:
        """The files in a snapshot, each tagged added/modified/unchanged vs. prev."""

        def work(session: Session) -> list[FileEntry]:
            snapshot = self._require(session, owner_id, snapshot_id)
            manifest = json.loads(snapshot.manifest_json)
            prev = self._previous(session, snapshot)
            prev_manifest = json.loads(prev.manifest_json) if prev else {}
            entries: list[FileEntry] = []
            for path in sorted(manifest):
                old = prev_manifest.get(path)
                if old is None:
                    status = "added"
                elif old != manifest[path]:
                    status = "modified"
                else:
                    status = "unchanged"
                entries.append(FileEntry(path=path, status=status))
            return entries

        return await in_session(self._engine, work)

    async def file_bytes(self, owner_id: str, snapshot_id: str, path: str) -> bytes:
        def work(session: Session) -> bytes:
            snapshot = self._require(session, owner_id, snapshot_id)
            manifest = json.loads(snapshot.manifest_json)
            sha = manifest.get(path)
            if sha is None:
                raise NotFoundError(f"path {path!r} not in snapshot {snapshot_id!r}")
            return self._blob_bytes(session, owner_id, sha)

        return await in_session(self._engine, work)

    async def diff(
        self, owner_id: str, snapshot_id: str, base_id: str | None = None
    ) -> list[FileDiff]:
        """Unified diffs of the files that changed between ``base`` (default: the
        previous snapshot) and this one. Binary files report status only."""

        def work(session: Session) -> list[FileDiff]:
            snapshot = self._require(session, owner_id, snapshot_id)
            manifest = json.loads(snapshot.manifest_json)
            base = (
                self._require(session, owner_id, base_id)
                if base_id is not None
                else self._previous(session, snapshot)
            )
            base_manifest = json.loads(base.manifest_json) if base else {}
            diffs: list[FileDiff] = []
            for path in sorted(set(manifest) | set(base_manifest)):
                old_sha, new_sha = base_manifest.get(path), manifest.get(path)
                if old_sha == new_sha:
                    continue
                if old_sha is None:
                    status = "added"
                elif new_sha is None:
                    status = "removed"
                else:
                    status = "modified"
                old_text = self._text(session, owner_id, old_sha)
                new_text = self._text(session, owner_id, new_sha)
                if old_text is None or new_text is None:
                    diffs.append(FileDiff(path=path, status=status, diff=""))  # binary
                    continue
                body = "".join(
                    difflib.unified_diff(
                        old_text.splitlines(keepends=True),
                        new_text.splitlines(keepends=True),
                        fromfile=f"a/{path}",
                        tofile=f"b/{path}",
                    )
                )
                diffs.append(FileDiff(path=path, status=status, diff=body))
            return diffs

        return await in_session(self._engine, work)

    async def delete_for_conversation(self, owner_id: str, conversation_id: str) -> None:
        """Drop a conversation's snapshots and any blob no remaining snapshot needs."""

        def work(session: Session) -> None:
            snapshots = session.exec(
                select(WorkspaceSnapshot)
                .where(WorkspaceSnapshot.owner_id == owner_id)
                .where(WorkspaceSnapshot.conversation_id == conversation_id)
            ).all()
            if not snapshots:
                return
            freed: set[str] = set()
            for snapshot in snapshots:
                freed |= set(json.loads(snapshot.manifest_json).values())
                session.delete(snapshot)
            session.flush()
            still_used: set[str] = set()
            remaining = session.exec(
                select(WorkspaceSnapshot.manifest_json).where(
                    WorkspaceSnapshot.owner_id == owner_id
                )
            ).all()
            for manifest_json in remaining:
                still_used |= set(json.loads(manifest_json).values())
            orphans = freed - still_used
            if orphans:
                session.exec(
                    delete(WorkspaceBlob)
                    .where(WorkspaceBlob.owner_id == owner_id)
                    .where(WorkspaceBlob.sha256.in_(orphans))  # type: ignore[attr-defined]
                )

        await in_session(self._engine, work)

    # -- internals ------------------------------------------------------------
    @staticmethod
    def _require(session: Session, owner_id: str, snapshot_id: str) -> WorkspaceSnapshot:
        row = session.get(WorkspaceSnapshot, snapshot_id)
        if row is None or row.owner_id != owner_id:
            raise NotFoundError(f"snapshot {snapshot_id!r} not found")
        return row

    @staticmethod
    def _previous(session: Session, snapshot: WorkspaceSnapshot) -> WorkspaceSnapshot | None:
        return session.exec(
            select(WorkspaceSnapshot)
            .where(WorkspaceSnapshot.owner_id == snapshot.owner_id)
            .where(WorkspaceSnapshot.conversation_id == snapshot.conversation_id)
            .where(WorkspaceSnapshot.created_at < snapshot.created_at)
            .order_by(WorkspaceSnapshot.created_at.desc())  # type: ignore[attr-defined]
        ).first()

    def _blob_bytes(self, session: Session, owner_id: str, sha: str) -> bytes:
        row = session.exec(
            select(WorkspaceBlob)
            .where(WorkspaceBlob.owner_id == owner_id)
            .where(WorkspaceBlob.sha256 == sha)
        ).first()
        if row is None:
            raise NotFoundError(f"blob {sha!r} not found")
        return self._vault.decrypt_bytes(row.blob_enc)

    def _text(self, session: Session, owner_id: str, sha: str | None) -> str | None:
        """The blob's text, or ``None`` for a missing/binary blob (no diff body)."""
        if sha is None:
            return ""  # absent on one side → an empty file for the diff
        try:
            return self._blob_bytes(session, owner_id, sha).decode("utf-8")
        except UnicodeDecodeError:
            return None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stats(prev: dict[str, str], curr: dict[str, str]) -> dict[str, int]:
    added = sum(1 for p in curr if p not in prev)
    removed = sum(1 for p in prev if p not in curr)
    modified = sum(1 for p in curr if p in prev and prev[p] != curr[p])
    return {"added": added, "modified": modified, "removed": removed}


def _to_view(row: WorkspaceSnapshot) -> SnapshotView:
    stats = json.loads(row.stats_json)
    added, modified, removed = (stats.get(k, 0) for k in ("added", "modified", "removed"))
    return SnapshotView(
        id=row.id,
        conversation_id=row.conversation_id,
        title=row.title,
        created_at=row.created_at,
        files_changed=added + modified + removed,
        summary=f"+{added} ~{modified} -{removed}",
        stats=stats,
    )
