/**
 * Workspace snapshot accessors (git-style history).
 *
 * The viewport reads a selected snapshot's file tree, a file's bytes, and the per-file
 * diffs through these. Auth-gated like the other `/views` endpoints — which is why the
 * bytes come back through the bearer-aware blob fetch and `snapshotFilePath` hands out a
 * *path* rather than a URL: an `<iframe>` or an `<img>` cannot carry the token, so a bare
 * `src` would 401.
 */

import { api } from "~/lib/api";
import type { SnapshotDiff, SnapshotFile } from "../model";
import type { SnapshotDiffDTO, SnapshotFileDTO } from "./wire";

/** The files in a snapshot's tree, each with its change status vs. the prior snapshot. */
export async function fetchSnapshotFiles(
  snapshotId: string,
): Promise<SnapshotFile[]> {
  const rows = await api.get<SnapshotFileDTO[]>(
    `/views/snapshots/${snapshotId}/files`,
  );
  return rows.map((r) => ({ path: r.path, status: r.status }));
}

/** A snapshot file's text content. Auth-gated, so the bytes come through the
 *  bearer-aware blob fetch, then decoded as text. */
export async function fetchSnapshotFileText(
  snapshotId: string,
  path: string,
): Promise<string> {
  const blob = await api.getBlob(snapshotFilePath(snapshotId, path));
  return blob.text();
}

/** The path to a snapshot file's raw bytes — fed to the blob fetch / blob-URL hook
 *  (an `<iframe>` can't carry the bearer, so never used as a bare src). */
export function snapshotFilePath(snapshotId: string, path: string): string {
  return `/views/snapshots/${snapshotId}/file?path=${encodeURIComponent(path)}`;
}

/** The per-file unified diffs for a snapshot against a base (empty `diff` for binary
 *  files). With no `baseId`, the backend diffs against the immediately-previous
 *  snapshot; pass an explicit snapshot id to compare against any prior version. */
export async function fetchSnapshotDiffs(
  snapshotId: string,
  baseId?: string,
): Promise<SnapshotDiff[]> {
  const query = baseId ? `?base=${encodeURIComponent(baseId)}` : "";
  const rows = await api.get<SnapshotDiffDTO[]>(
    `/views/snapshots/${snapshotId}/diff${query}`,
  );
  return rows.map((r) => ({ path: r.path, status: r.status, diff: r.diff }));
}
