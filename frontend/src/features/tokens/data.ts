import { createResource, createSignal, type Resource } from "solid-js";
import { api } from "~/lib/api";
import type { ServiceCredential } from "./model";

interface CredentialView {
  service: string;
  label: string;
  purpose: string;
  docs_url: string;
  has_key: boolean;
}

/** The single snake_case→camel mapper for a credential row. */
function toCredential(dto: CredentialView): ServiceCredential {
  return {
    service: dto.service,
    label: dto.label,
    purpose: dto.purpose,
    docsUrl: dto.docs_url,
    hasKey: dto.has_key,
  };
}

const [tick, setTick] = createSignal(0);

async function fetchCredentials(): Promise<ServiceCredential[]> {
  const rows = await api.get<CredentialView[]>("/credentials");
  return rows.map(toCredential);
}

export function useCredentials(): Resource<ServiceCredential[]> {
  const [data] = createResource(tick, fetchCredentials);
  return data;
}

/** Store (or replace) the key for a service. The plaintext is sent once and sealed
 *  server-side; it is never read back. */
export async function setCredential(
  service: string,
  apiKey: string,
): Promise<void> {
  await api.put(`/credentials/${service}`, { api_key: apiKey });
  setTick((n) => n + 1);
}

export async function clearCredential(service: string): Promise<void> {
  await api.del(`/credentials/${service}`);
  setTick((n) => n + 1);
}
