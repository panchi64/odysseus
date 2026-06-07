import { createResource, type Resource } from "solid-js";
import type { Skill } from "./model";
import { mockSkills } from "./mocks";

async function fetchSkills(): Promise<Skill[]> {
  return mockSkills;
}

async function fetchSkill(id: string): Promise<Skill | undefined> {
  return mockSkills.find((s) => s.id === id);
}

export function useSkills(): Resource<Skill[]> {
  const [data] = createResource(fetchSkills);
  return data;
}

/** Single skill for the editor. Resolves `undefined` for an unknown id (the
 *  editor renders a not-found state). Phase 2 swaps the body for an API call. */
export function useSkillDetail(id: () => string): Resource<Skill | undefined> {
  const [data] = createResource(id, fetchSkill);
  return data;
}
