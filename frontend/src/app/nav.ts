import type { IconName } from "~/ui";
import type { PrivilegeTier } from "~/lib/types";

/**
 * The single source of truth for primary navigation. The Sidebar renders this;
 * route files mirror the `href`s. Adding a surface = add an entry here + the
 * matching route file + feature folder.
 */
export interface NavItem {
  label: string;
  href: string;
  icon: IconName;
  tier: PrivilegeTier;
}

export interface NavSection {
  /** Section heading, uppercase. */
  title: string;
  items: NavItem[];
}

export const NAV: NavSection[] = [
  {
    title: "Conversation",
    items: [
      { label: "Chat", href: "/chat", icon: "terminal", tier: "open" },
      { label: "Research", href: "/research", icon: "research", tier: "open" },
      { label: "Compare", href: "/compare", icon: "compare", tier: "open" },
    ],
  },
  {
    title: "Knowledge",
    items: [
      { label: "Documents", href: "/documents", icon: "file", tier: "user" },
      { label: "Memory", href: "/memory", icon: "database", tier: "user" },
      { label: "Skills", href: "/skills", icon: "layers", tier: "user" },
      { label: "Gallery", href: "/gallery", icon: "image", tier: "user" },
      { label: "Uploads", href: "/uploads", icon: "upload", tier: "user" },
      { label: "Knowledge Base", href: "/rag", icon: "library", tier: "user" },
      { label: "Code Runner", href: "/code", icon: "code", tier: "open" },
      { label: "Signatures", href: "/signatures", icon: "pen", tier: "user" },
    ],
  },
  {
    title: "Communication",
    items: [
      { label: "Email", href: "/email", icon: "mail", tier: "user" },
      { label: "Calendar", href: "/calendar", icon: "calendar", tier: "user" },
      { label: "Contacts", href: "/contacts", icon: "users", tier: "user" },
      { label: "Notes", href: "/notes", icon: "note", tier: "open" },
      { label: "Tasks", href: "/tasks", icon: "clock", tier: "open" },
    ],
  },
  {
    title: "Models & Infra",
    items: [
      {
        label: "Cookbook",
        href: "/models/cookbook",
        icon: "cpu",
        tier: "admin",
      },
      {
        label: "Embedding",
        href: "/models/embedding",
        icon: "grid",
        tier: "admin",
      },
      { label: "MCP", href: "/mcp", icon: "plug", tier: "admin" },
      {
        label: "Integrations",
        href: "/integrations",
        icon: "link",
        tier: "admin",
      },
      { label: "Speech", href: "/speech", icon: "mic", tier: "admin" },
      { label: "Health", href: "/health", icon: "activity", tier: "admin" },
    ],
  },
  {
    title: "Security & Ops",
    items: [
      { label: "Settings", href: "/settings", icon: "settings", tier: "open" },
      { label: "Users", href: "/admin/users", icon: "user", tier: "admin" },
      {
        label: "API Tokens",
        href: "/admin/tokens",
        icon: "key",
        tier: "admin",
      },
      { label: "Vault", href: "/vault", icon: "lock", tier: "admin" },
      { label: "Backup", href: "/backup", icon: "archive", tier: "admin" },
      { label: "Shell", href: "/shell", icon: "terminal", tier: "admin" },
    ],
  },
];
