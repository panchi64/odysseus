import { createResource, type Resource } from "solid-js";
import type { McpServer } from "./model";
import { mockMcpServers } from "./mocks";

async function fetchMcpServers(): Promise<McpServer[]> {
  return mockMcpServers;
}

export function useMcpServers(): Resource<McpServer[]> {
  const [data] = createResource(fetchMcpServers);
  return data;
}
