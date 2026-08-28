/** Integrations feature data contracts. */

export type IntegrationStatus = "ok" | "untested" | "error";

/** One thing a connector can do, exposed to the agent as its own tool so it can be
 *  described and trusted separately from its siblings. */
export interface IntegrationAction {
  name: string;
  method: string;
  path: string;
  description: string;
  /** Whether the action is offered to the agent at all. */
  enabled: boolean;
  /** Whether it may run without pausing for approval. */
  trusted: boolean;
}

/** A connector the operator could configure, before they have. */
export interface IntegrationPreset {
  id: string;
  name: string;
  category: string;
  description: string;
  baseUrl: string;
  credentialRequired: boolean;
  actions: string[];
}

export interface Integration {
  id: string;
  name: string;
  /** The preset this connector was instantiated from — its kind. */
  type: string;
  baseUrl: string;
  configured: boolean;
  status: IntegrationStatus;
  /** Whether the operator has switched the whole connector off. */
  enabled: boolean;
  actions: IntegrationAction[];
  lastTestedAt?: string;
  description?: string;
  /** Why the last test failed, set when status === "error". */
  errorMessage?: string;
  /** Whether an API key / credential is required (vs. optional) for this connector. */
  credentialRequired?: boolean;
}
