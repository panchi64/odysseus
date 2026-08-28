/** Backup / restore feature data contracts. */

export interface BackupManifestItem {
  name: string;
  count: number;
}

export interface BackupManifest {
  createdAt: string;
  items: BackupManifestItem[];
}

/** A selectable backup section. Deliberately an open string rather than a union:
 *  the backend discovers the groups from its own models and reports them on
 *  `/backup/contents`, so a closed list here would be a second, staler menu. */
export type BackupInclude = string;

/** What an export would contain if taken right now. */
export interface BackupContents {
  sections: BackupInclude[];
  items: BackupManifestItem[];
}

/** The encrypted archive itself — opaque to the frontend, which only relays it
 *  between the backend and a file on disk. */
export type BackupEnvelope = Record<string, unknown>;

export interface BackupExport {
  envelope: BackupEnvelope;
  manifest: BackupManifest;
}

/** What a merge actually did, per section. `unknown` names groups the file carried
 *  that this build has no table for — reported so a partial restore is never silent. */
export interface BackupImportReport {
  imported: Record<string, number>;
  skipped: Record<string, number>;
  unknown: string[];
}
