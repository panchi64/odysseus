/** The command catalog seam — one read, mapped, and nothing decided here.
 *
 *  Filtering and ranking are deliberately absent. The backend narrows the catalog on
 *  facts only it holds (a withheld toolset, a thread that does not exist yet) and the
 *  *matching* of a typed query against it is the one thing left — which stays here only
 *  because it is presentation, and is written as such: a plain, testable ranking over
 *  rows that have already been decided.
 */

import { createResource, type Resource } from "solid-js";
import { api } from "~/lib/api";
import type { SessionMode } from "~/lib/modes";
import type { CommandCatalog } from "./model";

interface CatalogOut {
  groups: { id: string; label: string; order: number }[];
  commands: {
    name: string;
    qualifiedName: string;
    group: string;
    title: string;
    description: string;
    argumentHint: string | null;
    kind: string;
    actionId: string | null;
    actionArgument: { required: boolean; choices: string[] } | null;
    shadowedBy: string | null;
  }[];
}

function toCatalog(dto: CatalogOut): CommandCatalog {
  return {
    groups: dto.groups,
    commands: dto.commands.map((row) => ({
      ...row,
      kind: row.kind as CommandCatalog["commands"][number]["kind"],
      actionId: row.actionId as CommandCatalog["commands"][number]["actionId"],
    })),
  };
}

async function fetchCatalog(
  key: readonly [SessionMode, string | null],
): Promise<CommandCatalog> {
  const [mode, conversationId] = key;
  const query = new URLSearchParams({ mode });
  // Presence, not identity: the backend drops the actions that need a thread to act on
  // when there is none, so a launchpad composer is simply offered fewer rows.
  if (conversationId) query.set("conversation_id", conversationId);
  return toCatalog(await api.get<CatalogOut>(`/commands?${query}`));
}

/** The commands offerable in this composer. Re-reads when the mode or the thread
 *  changes, since both narrow what the backend will offer. */
export function useCommands(
  mode: () => SessionMode,
  conversationId: () => string | null,
): Resource<CommandCatalog> {
  const [data] = createResource(
    () => [mode(), conversationId()] as const,
    fetchCatalog,
  );
  return data;
}
