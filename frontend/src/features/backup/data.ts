import { createResource, createSignal, type Resource } from "solid-js";
import { api } from "~/lib/api";
import type {
  BackupContents,
  BackupEnvelope,
  BackupExport,
  BackupImportReport,
  BackupInclude,
  BackupManifest,
} from "./model";

/* ── Manifest + contents (the seam) ───────────────────────────────────────── */

const [tick, setTick] = createSignal(0);

/** The last export the operator took, or null if they never have — the backend
 *  reports the absence rather than inventing one, and the screen renders its own
 *  empty state from that. */
export function useLastBackup(): Resource<BackupManifest | null> {
  const [data] = createResource(tick, () =>
    api.get<BackupManifest | null>("/backup/manifest"),
  );
  return data;
}

/** The groups that actually exist on this host and their current counts. The
 *  export checklist is rendered from this, never from a hardcoded list. */
export function useBackupContents(): Resource<BackupContents> {
  const [data] = createResource(tick, () =>
    api.get<BackupContents>("/backup/contents"),
  );
  return data;
}

/* ── Mutations ────────────────────────────────────────────────────────────── */

/**
 * Take an export, encrypted under `secret` alone — the recovery passphrase is
 * separate from the login password and is not stored anywhere, so losing it makes
 * the file unrecoverable. `include` omitted ⇒ every section.
 *
 * The envelope comes back as a JSON object rather than a file download; the caller
 * serializes it to disk with the bytes already in hand.
 */
export async function exportBackup(
  secret: string,
  include?: BackupInclude[],
): Promise<BackupExport> {
  const result = await api.post<BackupExport>("/backup/export", {
    secret,
    ...(include ? { include } : {}),
  });
  setTick((n) => n + 1);
  return result;
}

/**
 * Merge an archive into this host. Never an overwrite: records that already exist
 * are skipped, so importing the same file twice changes nothing the second time.
 * A wrong secret answers 400, a malformed archive 422.
 */
export async function importBackup(
  secret: string,
  envelope: BackupEnvelope,
  include?: BackupInclude[],
): Promise<BackupImportReport> {
  const report = await api.post<BackupImportReport>("/backup/import", {
    secret,
    envelope,
    ...(include ? { include } : {}),
  });
  setTick((n) => n + 1);
  return report;
}
