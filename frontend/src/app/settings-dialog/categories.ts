import type { IconName } from "~/ui";

/**
 * One configuration category — a row in the dialog's left column, and the pane
 * that appears on the right when it is picked.
 *
 * `id` is what the URL carries (`?settings=<id>`), so it is a stable slug and
 * not a label: renaming a category must not break a bookmark.
 */
export interface SettingsCategory {
  id: string;
  /** Left-column label, uppercase — a category, in the machine's register. */
  label: string;
  icon: IconName;
  /** One line under the pane's title, and matched when searching the dialog. */
  description: string;
  /** The sections stacked in the pane, top to bottom, by id. Each id has a
   *  renderer in `SettingsPane.tsx`, which warns in dev when it is handed one it
   *  does not know — the two files cannot be checked against each other in a
   *  unit test, because importing the renderer map constructs every feature's
   *  resources at module load and there is no DOM here to hold them.
   *
   *  Titles are NOT repeated here: every section component already carries its
   *  own `Panel label` or `PageHeader variant="section"`, and a second copy of
   *  the title in this file would be the one that goes stale. */
  sections: string[];
}

/**
 * The six categories, and nothing else. This file is **data** — the same
 * discipline `nav/areas.ts` keeps: what exists and how it is labelled lives
 * here, and the components that render it derive everything else.
 *
 * Ordering is deliberate rather than alphabetical: GENERAL first because it is
 * what an operator opens the dialog for most often, SYSTEM last because it is
 * where you go when something is already wrong.
 */
export const SETTINGS_CATEGORIES: SettingsCategory[] = [
  {
    id: "general",
    label: "GENERAL",
    icon: "sun",
    description: "How the workspace looks and how conversations behave",
    sections: ["general.appearance", "general.chat", "general.offline"],
  },
  {
    id: "agent",
    label: "AGENT",
    icon: "system",
    description: "The capabilities and instructions the agent can reach for",
    sections: ["agent.tools", "agent.search", "agent.skills", "agent.projects"],
  },
  {
    id: "memory",
    label: "MEMORY",
    icon: "database",
    description: "The long-term facts the assistant remembers about you",
    sections: ["memory.facts"],
  },
  {
    id: "models",
    label: "MODELS",
    icon: "cpu",
    description:
      "Which model answers, and the endpoints they are reached through",
    sections: ["models.roles"],
  },
  {
    id: "security",
    label: "SECURITY",
    icon: "lock",
    description: "Secrets, and the keys in and out of this workspace",
    sections: [
      "security.vault",
      "security.service-keys",
      "security.access-tokens",
    ],
  },
  {
    id: "system",
    label: "SYSTEM",
    icon: "settings",
    description: "Connections, backups, and the state of the machine",
    sections: ["system.integrations", "system.backup", "system.health"],
  },
];

/** The category a `?settings=` value names, or undefined when it names none —
 *  a stale bookmark or a hand-typed slug lands on the first category rather
 *  than on an empty pane. */
export function categoryById(id: string | undefined): SettingsCategory {
  return SETTINGS_CATEGORIES.find((c) => c.id === id) ?? SETTINGS_CATEGORIES[0];
}

/** Every section id across every category — what the renderer map is checked
 *  against. */
export function allSectionIds(): string[] {
  return SETTINGS_CATEGORIES.flatMap((c) => c.sections);
}
