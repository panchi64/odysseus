import { createResource, type Resource } from "solid-js";
import type { Contact } from "./model";
import { mockContacts } from "./mocks";

async function fetchContacts(): Promise<Contact[]> {
  return mockContacts;
}

export function useContacts(): Resource<Contact[]> {
  const [data] = createResource(fetchContacts);
  return data;
}
