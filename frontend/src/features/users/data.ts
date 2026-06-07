import { createResource, type Resource } from "solid-js";
import type { ManagedUser } from "./model";
import { mockUsers } from "./mocks";

async function fetchUsers(): Promise<ManagedUser[]> {
  return mockUsers;
}

export function useUsers(): Resource<ManagedUser[]> {
  const [data] = createResource(fetchUsers);
  return data;
}
