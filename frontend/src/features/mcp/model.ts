/** MCP Connections feature data contracts. */

export type McpTransport = "stdio" | "http";
export type McpStatus = "connected" | "error" | "disconnected";

export interface McpTool {
  name: string;
  description: string;
  enabled: boolean;
}

export interface McpServer {
  id: string;
  name: string;
  transport: McpTransport;
  url: string;
  status: McpStatus;
  tools: McpTool[];
  authRequired?: boolean;
}
