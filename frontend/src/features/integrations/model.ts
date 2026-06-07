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
}
