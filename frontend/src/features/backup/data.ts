import { createResource, type Resource } from "solid-js";
import type { BackupManifest } from "./model";
import { mockLastBackup } from "./mocks";

async function fetchLastBackup(): Promise<BackupManifest> {
  return mockLastBackup;
}

export function useLastBackup(): Resource<BackupManifest> {
  const [data] = createResource(fetchLastBackup);
  return data;
}
