/** MCP Connections feature data contracts. */

/** "http" is MCP's Streamable HTTP; "sse" is the older server-sent-events transport. */
export type McpTransport = "stdio" | "sse" | "http";
export type McpStatus = "connected" | "error" | "disconnected";

export interface McpTool {
  name: string;
  description: string;
  /** Whether the tool is offered to the agent at all. Off ⇒ it never reaches the model. */
  enabled: boolean;
  /** Whether it may run without pausing for approval. Off ⇒ every call asks first — the
   *  default for anything external, granted one tool at a time and never per server. */
  trusted: boolean;
}

export interface McpAuthCredentials {
  method: "api_key" | "basic" | "bearer";
  /** API key / bearer token value. */
  token?: string;
  /** Basic auth username. */
  username?: string;
  /** Basic auth password. */
  password?: string;
}

export interface McpServer {
  id: string;
  name: string;
  /** Namespaces this server's tools for the agent (`external_{slug}_{tool}`). */
  slug: string;
  transport: McpTransport;
  /** The endpoint for the HTTP transports, the command line for stdio — the server's
   *  address either way, so the card has one field to show. */
  url: string;
  status: McpStatus;
  tools: McpTool[];
  /** Whether the operator has switched the whole server off. */
  enabled: boolean;
  authRequired?: boolean;
  /** Whether a credential is stored. The value itself is never returned. */
  hasCredentials: boolean;
  /** Names of the sealed environment variables set for a stdio server — the values,
   *  like credentials, never come back. */
  envKeys: string[];
  /** Last error message, set when status === "error". */
  errorMessage?: string;
  /** ISO timestamp of the last error. */
  errorAt?: string;
}
