import { createResource, type Resource } from "solid-js";
import type { Signature } from "./model";
import { mockSignatures } from "./mocks";

async function fetchSignatures(): Promise<Signature[]> {
  return mockSignatures;
}

export function useSignatures(): Resource<Signature[]> {
  const [data] = createResource(fetchSignatures);
  return data;
}
