/** Integrations feature data contracts. */

export type IntegrationStatus = "ok" | "untested" | "error";

export interface Integration {
  id: string;
  name: string;
  type: string;
  baseUrl: string;
  configured: boolean;
  status: IntegrationStatus;
  lastTestedAt?: string;
  description?: string;
  /** Whether an API key / credential is required (vs. optional) for this connector. */
  credentialRequired?: boolean;
}
