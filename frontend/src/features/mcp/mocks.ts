import type { McpServer } from "./model";

export const mockMcpServers: McpServer[] = [
  {
    id: "mcp-1",
    name: "Odysseus Memory",
    transport: "stdio",
    url: "odysseus-mcp-memory",
    status: "connected",
    tools: [
      {
        name: "memory.store",
        description: "Store a fact or snippet into long-term memory.",
        enabled: true,
      },
      {
        name: "memory.search",
        description: "Semantic search over stored memories.",
        enabled: true,
      },
      {
        name: "memory.delete",
        description: "Remove a memory by ID.",
        enabled: false,
      },
    ],
  },
  {
    id: "mcp-2",
    name: "Odysseus RAG",
    transport: "stdio",
    url: "odysseus-mcp-rag",
    status: "connected",
    tools: [
      {
        name: "rag.search",
        description: "Retrieve relevant document chunks.",
        enabled: true,
      },
      {
        name: "rag.ingest",
        description: "Ingest a file into the vector store.",
        enabled: true,
      },
    ],
  },
  {
    id: "mcp-3",
    name: "Email / Calendar",
    transport: "stdio",
    url: "odysseus-mcp-email",
    status: "connected",
    authRequired: true,
    tools: [
      {
        name: "email.list",
        description: "List recent emails from IMAP.",
        enabled: true,
      },
      {
        name: "email.send",
        description: "Send an email via SMTP.",
        enabled: true,
      },
      {
        name: "calendar.events",
        description: "List upcoming calendar events.",
        enabled: true,
      },
      {
        name: "calendar.create",
        description: "Create a calendar event.",
        enabled: false,
      },
    ],
  },
  {
    id: "mcp-4",
    name: "Image Generation",
    transport: "http",
    url: "http://localhost:7100/mcp",
    status: "error",
    tools: [
      {
        name: "image.generate",
        description: "Generate an image from a prompt.",
        enabled: false,
      },
    ],
  },
  {
    id: "mcp-5",
    name: "Custom Remote Server",
    transport: "http",
    url: "https://mcp.example.com/v1",
    status: "disconnected",
    tools: [],
  },
];
