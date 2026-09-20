/**
 * A View version, and the inline chip that references it.
 *
 * Pure DTO→seam translations shared by the cold read (conversation detail) and the warm
 * stream (`view.snapshot`) — a version chip has to look identical whether the operator
 * watched it arrive or reloaded into it, and one function producing both is the only way
 * to guarantee that.
 */

import type { ViewSnapshotRef, ViewVersionBlock } from "../model";
import type { ViewSnapshotDTO } from "./wire";

/** Map a View version DTO/event to the seam type. Shared by the cold read
 *  (conversation detail) and the warm stream (`view.snapshot`). */
export function toViewSnapshotRef(dto: ViewSnapshotDTO): ViewSnapshotRef {
  return {
    snapshotId: dto.snapshot_id,
    title: dto.title ?? undefined,
    createdAt: dto.created_at,
    filesChanged: dto.files_changed,
    summary: dto.summary,
    preview:
      dto.preview_artifact_id && dto.preview_kind
        ? { kind: dto.preview_kind, artifactId: dto.preview_artifact_id }
        : null,
    keeper: dto.keeper ?? false,
  };
}

/** The inline transcript chip for a version the agent `show`ed — references the
 *  conversation-scoped version by id. Shared by the cold read and the warm stream. */
export function toVersionChipBlock(
  messageId: string,
  ref: {
    snapshotId: string;
    title?: string;
    previewKind?: ViewVersionBlock["previewKind"];
  },
): ViewVersionBlock {
  return {
    kind: "view_version",
    id: `${messageId}-${ref.snapshotId}`,
    snapshotId: ref.snapshotId,
    title: ref.title,
    previewKind: ref.previewKind,
  };
}
