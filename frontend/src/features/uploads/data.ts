import { createResource, type Resource } from "solid-js";
import type { Upload } from "./model";
import { mockUploads } from "./mocks";

async function fetchUploads(): Promise<Upload[]> {
  return mockUploads;
}

export function useUploads(): Resource<Upload[]> {
  const [data] = createResource(fetchUploads);
  return data;
}
