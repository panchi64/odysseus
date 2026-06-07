import { createResource, type Resource } from "solid-js";
import type { Note } from "./model";
import { mockNotes } from "./mocks";

async function fetchNotes(): Promise<Note[]> {
  return mockNotes;
}

export function useNotes(): Resource<Note[]> {
  const [data] = createResource(fetchNotes);
  return data;
}
