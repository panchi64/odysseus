import type { IconName } from "~/ui";

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
  /** One-line capability description, shown as a hover tooltip. Keeps the rail
   *  free of inline micro-labels while still explaining unfamiliar names. */
  description: string;
  /** Optional ambient activity indicator. */
  indicator?: NavIndicator;
  /** Whether this surface is wired to the backend. Unconnected surfaces still
   *  render their mock screen but are marked in the rail and overlaid with a
   *  NOT CONNECTED banner. Defaults to false (mock-only). */
  connected?: boolean;
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
        connected: true,
        description: "Converse with local models and tool-using agents",
      },
      {
        label: "Research",
        href: "/research",
        icon: "research",
        description: "Run deep, multi-source research reports",
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
        description: "Write and edit documents with AI assistance",
      },
      {
        label: "Memory",
        href: "/memory",
        icon: "database",
        connected: true,
        description: "Long-term facts the assistant remembers about you",
      },
      {
        label: "Skills",
        href: "/skills",
        icon: "layers",
        description: "Reusable instructions and capabilities for agents",
      },
      {
        label: "Gallery",
        href: "/gallery",
        icon: "image",
        description: "Generated and uploaded images",
      },
      {
        label: "Uploads",
        href: "/uploads",
        icon: "upload",
        description: "Files you've uploaded for the assistant to use",
      },
      {
        label: "Knowledge Base",
        href: "/rag",
        icon: "library",
        description: "Searchable document collections for retrieval (RAG)",
      },
      {
        label: "Code Runner",
        href: "/code",
        icon: "code",
        description: "Run code snippets in a sandbox",
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
        description: "Read and send email",
      },
      {
        label: "Calendar",
        href: "/calendar",
        icon: "calendar",
        description: "View and manage your schedule",
      },
      {
        label: "Tasks",
        href: "/tasks",
        icon: "clock",
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
        description:
          "Serve and manage local models, embeddings, and side-by-side comparison",
      },
      {
        label: "MCP",
        href: "/mcp",
        icon: "plug",
        description: "Manage Model Context Protocol tool servers",
      },
      {
        label: "Integrations",
        href: "/integrations",
        icon: "link",
        description: "Connect external accounts and services",
      },
      {
        label: "Health",
        href: "/health",
        icon: "activity",
        description: "System status and service health",
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
        connected: true,
        description: "App preferences and configuration",
      },
      {
        label: "Users",
        href: "/admin/users",
        icon: "user",
        description: "Manage accounts and privileges",
      },
      {
        label: "API Tokens",
        href: "/admin/tokens",
        icon: "key",
        description: "Issue and revoke API access tokens",
      },
      {
        label: "Vault",
        href: "/vault",
        icon: "lock",
        description: "Encrypted storage for secrets and keys",
      },
      {
        label: "Backup",
        href: "/backup",
        icon: "archive",
        description: "Back up and restore your data",
      },
      {
        label: "Shell",
        href: "/shell",
        icon: "terminal",
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

/** Whether a route path is backed by the real backend (vs. a mock-only surface).
 *  Drives the NOT CONNECTED overlay. Matches a connected nav item's href exactly
 *  or as a path prefix (so detail routes like `/chat/x` count as connected). The
 *  home route (`/`) has no nav entry — it's the launchpad — but is itself
 *  connected (the composer/threads via the chat seam, the status panels via
 *  `/overview` + `/runs`), so it's treated as connected here. */
export function isConnectedRoute(
  pathname: string,
  nav: NavSection[] = NAV,
): boolean {
  if (pathname === "/") return true;
  return flattenNav(nav).some(
    ({ item }) =>
      item.connected &&
      (pathname === item.href || pathname.startsWith(`${item.href}/`)),
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
