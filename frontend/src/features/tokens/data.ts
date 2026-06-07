import { createResource, type Resource } from "solid-js";
import type { ApiToken } from "./model";
import { mockTokens } from "./mocks";

async function fetchTokens(): Promise<ApiToken[]> {
  return mockTokens;
}

export function useTokens(): Resource<ApiToken[]> {
  const [data] = createResource(fetchTokens);
  return data;
}
