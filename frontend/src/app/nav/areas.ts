import type { NavArea, NavPin } from "./types";

/**
 * The areas the switcher offers — every group of pages, and nothing else. A lone
 * destination belongs in `PINS` below, not here: an area with one item gives the
 * switcher a row that switches to nothing.
 *
 * An `href` must appear in exactly one area: the active area is derived from the
 * current path, so a duplicated href would make that derivation ambiguous.
 * Surfaces that belong to two stories (model endpoints are both configuration
 * and model setup) live in one area and are reached from the other by search.
 */
export const AREAS: NavArea[] = [
  {
    id: "knowledge",
    label: "KNOWLEDGE",
    icon: "library",
    description: "Everything the assistant can read, recall, and cite",
    items: [
      {
        label: "Knowledge Base",
        href: "/rag",
        icon: "library",
        connected: true,
        description:
          "The unified retrieval corpus — every source the assistant can search (RAG)",
      },
      {
        label: "Documents",
        href: "/documents",
        icon: "file",
        description: "Write and edit documents with AI assistance",
        connected: true,
      },
      {
        label: "Uploads",
        href: "/uploads",
        icon: "upload",
        description: "Files you've uploaded for the assistant to use",
        connected: true,
      },
      {
        label: "Gallery",
        href: "/gallery",
        icon: "image",
        connected: true,
        description: "Images from chat attachments and knowledge-base uploads",
      },
      {
        label: "Memory",
        href: "/memory",
        icon: "database",
        connected: true,
        description: "Long-term facts the assistant remembers about you",
      },
      {
        label: "Research",
        href: "/research",
        icon: "research",
        connected: true,
        description: "Deep, multi-source research reports, kept as reference",
      },
    ],
  },
  {
    id: "comms",
    label: "COMMS",
    icon: "mail",
    description: "Mail, schedule, and the agent's standing work",
    items: [
      {
        label: "Email",
        href: "/email",
        icon: "mail",
        description: "Read and send email",
        connected: true,
      },
      {
        label: "Calendar",
        href: "/calendar",
        icon: "calendar",
        connected: true,
        description: "View and manage your schedule",
      },
      {
        label: "Tasks",
        href: "/tasks",
        icon: "clock",
        connected: true,
        description: "Scheduled agent tasks and reminders",
      },
    ],
  },
  {
    id: "agent",
    label: "AGENT",
    icon: "system",
    description: "The capabilities and tools the agent can reach for",
    items: [
      {
        label: "Skills",
        href: "/skills",
        icon: "layers",
        connected: true,
        description: "Reusable instructions and capabilities for agents",
      },
      {
        label: "MCP",
        href: "/mcp",
        icon: "plug",
        connected: true,
        description: "Manage Model Context Protocol tool servers",
      },
      {
        label: "Code Runner",
        href: "/code",
        icon: "code",
        connected: true,
        description: "Run code snippets in a sandbox",
      },
      {
        label: "Shell",
        href: "/shell",
        icon: "terminal",
        connected: true,
        description: "Run shell commands on the host",
      },
      {
        label: "Tools",
        href: "/settings/tools",
        icon: "grid",
        connected: true,
        description:
          "The agent's built-in tools and the web-search providers behind them",
      },
    ],
  },
  {
    id: "models",
    label: "MODELS",
    icon: "cpu",
    description: "Serve, bind, and compare the models that do the work",
    items: [
      {
        label: "Get Started",
        href: "/models/cookbook/getstarted",
        icon: "play",
        connected: true,
        description: "The guided flow for connecting your first model",
      },
      {
        label: "Local Models",
        href: "/models/cookbook/local",
        icon: "cpu",
        connected: true,
        description:
          "Hardware fit, inference engines, and the download / serve lifecycle",
      },
      {
        label: "Embedding",
        href: "/models/cookbook/embedding",
        icon: "grid",
        connected: true,
        description: "Serve and bind the embedding model behind retrieval",
      },
      {
        label: "Compare",
        href: "/models/cookbook/compare",
        icon: "compare",
        connected: true,
        description: "Run the same prompt across models side by side",
      },
      {
        label: "Models",
        href: "/settings/models",
        icon: "reticle",
        connected: true,
        description:
          "Which model answers chat, runs background work, and powers recall — plus the endpoints they're reached through",
      },
    ],
  },
  {
    id: "security",
    label: "SECURITY",
    icon: "lock",
    description: "Secrets, and the keys in and out of this workspace",
    items: [
      {
        label: "Vault",
        href: "/vault",
        icon: "lock",
        description: "Encrypted storage for secrets and keys",
        connected: true,
      },
      // Two token surfaces pointing opposite ways — the labels have to say which is
      // which, because "API Tokens" reads as either one.
      {
        label: "Service Keys",
        href: "/admin/tokens",
        icon: "key",
        description:
          "Outbound — keys this system calls third-party services with (model benchmarks, HuggingFace)",
        connected: true,
      },
      {
        label: "Access Tokens",
        href: "/admin/access-tokens",
        icon: "key",
        description:
          "Inbound — scoped tokens your own clients call this API with",
        connected: true,
      },
    ],
  },
  {
    id: "system",
    label: "SYSTEM",
    icon: "settings",
    description: "Preferences, connections, and the state of the machine",
    items: [
      {
        label: "Appearance",
        href: "/settings/appearance",
        icon: "sun",
        connected: true,
        description: "Theme and how the workspace looks",
      },
      {
        label: "Chat",
        href: "/settings/chat",
        icon: "chat",
        connected: true,
        description: "Defaults for how conversations behave",
      },
      {
        label: "Offline Mode",
        href: "/settings/offline",
        icon: "cross",
        connected: true,
        description: "What stays available with no network",
      },
      {
        label: "Integrations",
        href: "/integrations",
        icon: "link",
        connected: true,
        description: "Connect external accounts and services",
      },
      {
        label: "Health",
        href: "/health",
        icon: "activity",
        description: "System status and service health",
      },
      {
        label: "Backup",
        href: "/backup",
        icon: "archive",
        description: "Back up and restore your data",
        connected: true,
      },
    ],
  },
];

/**
 * The two destinations that sit outside the switcher. Chat is where the work
 * happens and Settings is where you go when something is wrong — both are worth
 * a permanent row, and neither is a group of pages.
 *
 * Settings points into SYSTEM rather than owning a page of its own, so opening
 * it lands in that area with the rest of it listed.
 */
export const PINS: NavPin[] = [
  {
    slot: "top",
    item: {
      label: "Chat",
      href: "/chat",
      icon: "chat",
      connected: true,
      description: "Converse with local models and tool-using agents",
    },
  },
  {
    slot: "footer",
    item: {
      label: "Settings",
      href: "/settings/appearance",
      icon: "settings",
      connected: true,
      description: "Preferences, connections, and the state of the machine",
    },
  },
];
