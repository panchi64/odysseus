import { createResource, type Resource } from "solid-js";
import type { Skill } from "./model";
import { mockSkills } from "./mocks";

async function fetchSkills(): Promise<Skill[]> {
  return mockSkills;
}

export function useSkills(): Resource<Skill[]> {
  const [data] = createResource(fetchSkills);
  return data;
}
