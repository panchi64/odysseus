import { createResource, type Resource } from "solid-js";
import type { UserPreferences, TwoFactorState } from "./model";
import { mockPreferences, mockTwoFactorState } from "./mocks";

async function fetchPreferences(): Promise<UserPreferences> {
  return mockPreferences;
}

async function fetchTwoFactorState(): Promise<TwoFactorState> {
  return mockTwoFactorState;
}

export function usePreferences(): Resource<UserPreferences> {
  const [data] = createResource(fetchPreferences);
  return data;
}

export function useTwoFactorState(): Resource<TwoFactorState> {
  const [data] = createResource(fetchTwoFactorState);
  return data;
}
