/** Viewport derivation — the conversation's **View** as a list of items the
 *  side panel renders. Presentation-only: it reads the same blocks the transcript
 *  renders, so it is automatically thread-scoped and never a second source of
 *  truth. A View is the static **versions** (the comparable history) plus the
 *  latest **live head** (the interactive current state), which sorts last as the
 *  newest item. */

import type { IconName } from "~/ui";
import type {
  ChatMessage,
  ViewLiveRef,
  ViewSnapshotRef,
  ViewVersionRef,
} from "./model";

/** One thing on the View canvas: a static snapshot version, a workspace snapshot
 *  (git-style file tree), or the live head. */
export type ViewItem =
  | { key: string; kind: "version"; label: string; version: ViewVersionRef }
  | { key: string; kind: "snapshot"; label: string; snapshot: ViewSnapshotRef }
  | { key: string; kind: "live"; label: string; live: ViewLiveRef };

/** The selection key for the (single) live head. */
export const LIVE_KEY = "live";
/** The selection key for a static version — stable across warm + cold renders
 *  (both carry the same backend version id). */
export const versionKey = (versionId: string): string => `version-${versionId}`;
/** The selection key for a workspace snapshot — stable across warm + cold renders. */
export const snapshotKey = (snapshotId: string): string =>
  `snapshot-${snapshotId}`;

/** A coarse icon for a version chip, by render kind. */
export function versionIcon(kind: ViewVersionRef["kind"]): IconName {
  return kind === "image" ? "image" : kind === "html" ? "eye" : "file";
}

/** Collect a thread's View items in order: every static version, then every
 *  workspace snapshot, then the latest live head as the head (newest) item.
 *  Versions + snapshots are history; the live head is the head. Snapshots are
 *  conversation-scoped, so they arrive separately from the message blocks. */
export function collectViewItems(
  messages: ChatMessage[],
  snapshots: ViewSnapshotRef[] = [],
): ViewItem[] {
  const versions: ViewItem[] = [];
  let live: ViewItem | null = null;
  for (const m of messages) {
    for (const b of m.blocks ?? []) {
      if (b.kind === "view_version") {
        versions.push({
          key: versionKey(b.version.versionId),
          kind: "version",
          label: b.version.title || b.version.filename,
          version: b.version,
        });
      } else if (b.kind === "view_live") {
        live = {
          key: LIVE_KEY,
          kind: "live",
          label: b.live.title || "Live view",
          live: b.live,
        };
      }
    }
  }
  const snaps: ViewItem[] = snapshots.map((s, i) => ({
    key: snapshotKey(s.snapshotId),
    kind: "snapshot",
    label: s.title || `S${i + 1}`,
    snapshot: s,
  }));
  const history = [...versions, ...snaps];
  return live ? [...history, live] : history;
}

/* ── First-time-only auto-open ────────────────────────────────────────────────
   The viewport opens itself the first time a thread produces a View item, then
   never again for that thread — so a later manual close is respected. Session-
   scoped (a plain Set, not authoritative state) and module-level so it survives
   the screen remounting on navigation. */
const autoOpened = new Set<string>();

/** True at most once per conversation: the moment it first has View items, so the
 *  caller can open the viewport. Subsequent calls (more items, a manual close)
 *  return false. */
export function claimAutoOpen(conversationId: string): boolean {
  if (autoOpened.has(conversationId)) return false;
  autoOpened.add(conversationId);
  return true;
}
