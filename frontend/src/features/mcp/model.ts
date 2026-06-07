/** MCP Connections feature data contracts. */

export type McpTransport = "stdio" | "http";
export type McpStatus = "connected" | "error" | "disconnected";

export interface McpTool {
  name: string;
  description: string;
  enabled: boolean;
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
  transport: McpTransport;
  url: string;
  status: McpStatus;
  tools: McpTool[];
  authRequired?: boolean;
  /** Last error message, set when status === "error". */
  errorMessage?: string;
  /** ISO timestamp of the last error. */
  errorAt?: string;
  /** Credentials provided by the user for auth-required servers. */
  credentials?: McpAuthCredentials;
}
