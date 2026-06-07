import { createResource, type Resource } from "solid-js";
import type {
  HardwareInfo,
  ModelEntry,
  RunningServer,
  RemoteEndpoint,
} from "./model";
import {
  mockHardware,
  mockModels,
  mockServers,
  mockRemoteEndpoints,
} from "./mocks";

async function fetchHardware(): Promise<HardwareInfo> {
  return mockHardware;
}

async function fetchModels(): Promise<ModelEntry[]> {
  return mockModels;
}

async function fetchServers(): Promise<RunningServer[]> {
  return mockServers;
}

async function fetchRemoteEndpoints(): Promise<RemoteEndpoint[]> {
  return mockRemoteEndpoints;
}

export function useHardware(): Resource<HardwareInfo> {
  const [data] = createResource(fetchHardware);
  return data;
}

export function useCookbookModels(): Resource<ModelEntry[]> {
  const [data] = createResource(fetchModels);
  return data;
}

export function useRunningServers(): Resource<RunningServer[]> {
  const [data] = createResource(fetchServers);
  return data;
}

export function useRemoteEndpoints(): Resource<RemoteEndpoint[]> {
  const [data] = createResource(fetchRemoteEndpoints);
  return data;
}
