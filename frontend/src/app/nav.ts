import type { IconName } from "~/ui";
import type { PrivilegeTier } from "~/lib/types";

/**
 * The single source of truth for primary navigation. The Sidebar renders this;
 * route files mirror the `href`s. Adding a surface = add an entry here + the
 * matching route file + feature folder.
 */
/** Ambient activity state surfaced as a small semantic square on a nav item
 *  (e.g. unread mail, a degraded service). Carries meaning only — an item at
 *  rest has none, keeping the resting rail monochrome (design system §4). In
 *  Phase 1 these are mock; Phase 2 populates them from live data. */
export type NavIndicator = "nominal" | "info" | "warn" | "alert";

export interface NavItem {
  label: string;
  href: string;
  icon: IconName;
  tier: PrivilegeTier;
  /** One-line capability description, shown as a hover tooltip. Keeps the rail
   *  free of inline micro-labels while still explaining unfamiliar names. */
  description: string;
  /** Optional ambient activity indicator. */
  indicator?: NavIndicator;
}

export interface NavSection {
  /** Section heading, uppercase. */
  title: string;
  items: NavItem[];
  /** Collapse this section by default — used to fold rarely-touched infra/ops
   *  so the resting rail leads with everyday capabilities. */
  defaultCollapsed?: boolean;
}

export const NAV: NavSection[] = [
  {
    title: "Conversation",
    items: [
      {
        label: "Chat",
        href: "/chat",
        icon: "terminal",
        tier: "open",
        description: "Converse with local models and tool-using agents",
      },
      {
        label: "Research",
        href: "/research",
        icon: "research",
        tier: "open",
        description: "Run deep, multi-source research reports",
      },
      {
        label: "Compare",
        href: "/compare",
        icon: "compare",
        tier: "open",
        description: "Run one prompt across models side by side",
      },
    ],
  },
  {
    title: "Knowledge",
    items: [
      {
        label: "Documents",
        href: "/documents",
        icon: "file",
        tier: "user",
        description: "Write and edit documents with AI assistance",
      },
      {
        label: "Memory",
        href: "/memory",
        icon: "database",
        tier: "user",
        description: "Long-term facts the assistant remembers about you",
      },
      {
        label: "Skills",
        href: "/skills",
        icon: "layers",
        tier: "user",
        description: "Reusable instructions and capabilities for agents",
      },
      {
        label: "Gallery",
        href: "/gallery",
        icon: "image",
        tier: "user",
        description: "Generated and uploaded images",
      },
      {
        label: "Uploads",
        href: "/uploads",
        icon: "upload",
        tier: "user",
        description: "Files you've uploaded for the assistant to use",
      },
      {
        label: "Knowledge Base",
        href: "/rag",
        icon: "library",
        tier: "user",
        description: "Searchable document collections for retrieval (RAG)",
      },
      {
        label: "Code Runner",
        href: "/code",
        icon: "code",
        tier: "open",
        description: "Run code snippets in a sandbox",
      },
      {
        label: "Signatures",
        href: "/signatures",
        icon: "pen",
        tier: "user",
        description: "Saved signatures for documents and email",
      },
    ],
  },
  {
    title: "Communication",
    items: [
      {
        label: "Email",
        href: "/email",
        icon: "mail",
        tier: "user",
        description: "Read and send email",
        // indicator: mock unread state (Phase 1). Replaced by live data in Phase 2.
        indicator: "info",
      },
      {
        label: "Calendar",
        href: "/calendar",
        icon: "calendar",
        tier: "user",
        description: "View and manage your schedule",
      },
      {
        label: "Contacts",
        href: "/contacts",
        icon: "users",
        tier: "user",
        description: "Your address book",
      },
      {
        label: "Notes",
        href: "/notes",
        icon: "note",
        tier: "open",
        description: "Quick personal notes",
      },
      {
        label: "Tasks",
        href: "/tasks",
        icon: "clock",
        tier: "open",
        description: "To-dos and reminders",
      },
    ],
  },
  {
    title: "Models & Infra",
    defaultCollapsed: true,
    items: [
      {
        label: "Cookbook",
        href: "/models/cookbook",
        icon: "cpu",
        tier: "admin",
        description: "Serve and manage local models",
      },
      {
        label: "Embedding",
        href: "/models/embedding",
        icon: "grid",
        tier: "admin",
        description: "Configure the text-embedding model for search",
      },
      {
        label: "MCP",
        href: "/mcp",
        icon: "plug",
        tier: "admin",
        description: "Manage Model Context Protocol tool servers",
      },
      {
        label: "Integrations",
        href: "/integrations",
        icon: "link",
        tier: "admin",
        description: "Connect external accounts and services",
      },
      {
        label: "Speech",
        href: "/speech",
        icon: "mic",
        tier: "admin",
        description: "Text-to-speech and speech-to-text settings",
      },
      {
        label: "Health",
        href: "/health",
        icon: "activity",
        tier: "admin",
        description: "System status and service health",
        // indicator: mock service-health state (Phase 1). Replaced by live data in Phase 2.
        indicator: "warn",
      },
    ],
  },
  {
    title: "Security & Ops",
    defaultCollapsed: true,
    items: [
      {
        label: "Settings",
        href: "/settings",
        icon: "settings",
        tier: "open",
        description: "App preferences and configuration",
      },
      {
        label: "Users",
        href: "/admin/users",
        icon: "user",
        tier: "admin",
        description: "Manage accounts and privileges",
      },
      {
        label: "API Tokens",
        href: "/admin/tokens",
        icon: "key",
        tier: "admin",
        description: "Issue and revoke API access tokens",
      },
      {
        label: "Vault",
        href: "/vault",
        icon: "lock",
        tier: "admin",
        description: "Encrypted storage for secrets and keys",
      },
      {
        label: "Backup",
        href: "/backup",
        icon: "archive",
        tier: "admin",
        description: "Back up and restore your data",
      },
      {
        label: "Shell",
        href: "/shell",
        icon: "terminal",
        tier: "admin",
        description: "Run shell commands on the host",
      },
    ],
  },
];

/** An item paired with the section it belongs to — the unit search returns. */
export interface NavMatch {
  item: NavItem;
  section: NavSection;
}

/** Flatten the nav model into (item, section) pairs. */
export function flattenNav(nav: NavSection[] = NAV): NavMatch[] {
  return nav.flatMap((section) =>
    section.items.map((item) => ({ item, section })),
  );
}

/** Case-insensitive label search over the nav model. Empty query → no matches. */
export function searchNav(query: string, nav: NavSection[] = NAV): NavMatch[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return flattenNav(nav).filter(({ item }) =>
    item.label.toLowerCase().includes(q),
  );
}
