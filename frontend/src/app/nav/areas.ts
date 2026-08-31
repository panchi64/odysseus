import type { NavArea, NavPin } from "./types";

/**
 * The areas the rail still groups. There is exactly one, and that is the point:
 * the rail is the thread list now, and everything that was configuration moved
 * into the settings dialog (`app/settings-dialog/categories.ts`).
 *
 * COMMS survived as an area because its three surfaces are genuinely *places you
 * go and work* — an inbox, a schedule, a task list — not values you set. They
 * are pages for the same reason chat is.
 *
 * An `href` must appear in exactly one area: the active area is derived from the
 * current path, so a duplicated href would make that derivation ambiguous.
 */
export const AREAS: NavArea[] = [
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
];

/**
 * The destinations kept outside the one area.
 *
 * Chat sits first because the rail beneath it *is* chat — its thread list. The
 * two below it are the surfaces still worth a page and not mail: the corpus the
 * assistant reads from, and the compare bench. Each is a place with its own
 * screen, so a rail row is the honest affordance; none is a group, so none is an
 * area.
 *
 * Research is deliberately **not** here any more. It stopped being a surface that
 * produces reports and became a *mode a thread can be in*, so its home is the
 * thread list beneath Chat — a page of its own would list the same conversations
 * twice under two names.
 *
 * MCP is deliberately **not** here. Registering a tool server and deciding which
 * of its tools may run is configuration — a value you set and leave — so it is a
 * section of the settings dialog, beside the other connections. A pin for it
 * meant a permanent rail row for a page most operators open twice.
 *
 * Settings is deliberately **not** here. It opens the dialog rather than
 * navigating, so there is no `href` to pin, and the rail's footer renders it
 * directly.
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
    slot: "top",
    item: {
      label: "Knowledge Base",
      href: "/rag",
      icon: "library",
      connected: true,
      description:
        "The unified retrieval corpus — every source the assistant can search (RAG)",
    },
  },
  {
    slot: "top",
    item: {
      label: "Compare",
      href: "/compare",
      icon: "compare",
      connected: true,
      description: "Run the same prompt across models side by side",
    },
  },
];
