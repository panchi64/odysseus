/** Viewport derivation — the conversation's **View** as one consolidated list of
 *  **versions** the side panel renders. Presentation-only: it reads the same blocks
 *  the transcript renders (plus the conversation's snapshots), so it is automatically
 *  thread-scoped and never a second source of truth. Every entry is a version with a
 *  PREVIEW (rendered HTML) and a CODE representation; the newest is "Latest", and the
 *  live head — when a server is running — overlays the latest snapshot so that
 *  *live = the latest snapshot* (its preview is the running server, its code is that
 *  snapshot's files). */

import type { IconName } from "~/ui";
import type {
  ChatMessage,
  SnapshotFile,
  ViewDocumentRef,
  ViewLiveRef,
  ViewPreviewRef,
  ViewSnapshotRef,
} from "./model";

/** One version on the View canvas: a workspace `snapshot` (its code, plus how it
 *  previews — a static file by kind, or an auto-picked entry HTML page), optionally
 *  overlaid by the `live` head when a server is running. When there are no snapshots
 *  yet, a standalone `live` head is the lone entry. The panel renders PREVIEW vs CODE
 *  from whichever source is set. */
export interface ViewItem {
  key: string;
  /** Dropdown label, e.g. `V2 · Landing page` or `V3 · Landing page · live`. */
  label: string;
  /** The newest entry — the one the viewport follows when nothing is pinned. */
  isLatest: boolean;
  /** A workspace snapshot: preview = its stamped static file or auto entry HTML;
   *  code = file tree + diffs. */
  snapshot?: ViewSnapshotRef;
  /** The live running server. Overlays the latest snapshot (preview = the live
   *  iframe), or stands alone as its own entry when there are no snapshots. */
  live?: ViewLiveRef;
  /** A committed document version: preview = its markdown body; code = the raw body
   *  (plus a compare-vs-prior diff). An in-progress (version 0) ref carried here is
   *  the live-updating body streamed before its commit. */
  document?: ViewDocumentRef;
}

/** The selection key for the (single) live head — used when it stands alone. */
export const LIVE_KEY = "live";
/** The selection key for a workspace snapshot version — stable across warm + cold
 *  renders (both carry the same backend snapshot id). */
export const snapshotKey = (snapshotId: string): string =>
  `snapshot-${snapshotId}`;
/** The selection key for a document version — stable across warm + cold renders
 *  (both carry the same backend document id + version number). */
export const documentKey = (documentId: string, version: number): string =>
  `doc-${documentId}-v${version}`;

/** A coarse icon for a version chip, by its preview kind (null ⇒ a live/auto preview). */
export function versionIcon(
  kind: ViewPreviewRef["kind"] | null | undefined,
): IconName {
  return kind === "image" ? "image" : kind === "html" ? "eye" : "file";
}

/** True for an HTML file path (`.html` / `.htm`). */
function isHtmlPath(path: string): boolean {
  return /\.html?$/i.test(path);
}

/** Pick a snapshot's entry HTML file for the rendered preview: `index.html` if
 *  present, else the first HTML file, else none (the version has no page to render). */
export function pickEntryHtml(files: SnapshotFile[]): string | undefined {
  const html = files.filter((f) => isHtmlPath(f.path));
  if (html.length === 0) return undefined;
  const index = html.find((f) => /(^|\/)index\.html?$/i.test(f.path));
  return (index ?? html[0]).path;
}

/** The dropdown label for an entry: its position, an optional title, and a trailing
 *  `live`/`latest` tag on the newest. */
function entryLabel(item: ViewItem, n: number, isLatest: boolean): string {
  const title = (item.snapshot?.title ?? item.document?.title ?? "").trim();
  const parts = [`V${n}`];
  if (title) parts.push(title);
  // A live server, or a document whose body is still streaming (version 0), reads
  // "live"; any other newest entry reads "latest".
  const isLive = Boolean(item.live) || item.document?.version === 0;
  if (isLatest) parts.push(isLive ? "live" : "latest");
  return parts.join(" · ");
}

/** A version entry's mint time (ISO) — its snapshot's or document version's `createdAt` —
 *  used to order snapshots and document versions into one timeline. */
function itemCreatedAt(item: ViewItem): string {
  return item.snapshot?.createdAt ?? item.document?.createdAt ?? "";
}

/** Collect a thread's View as one ordered list of versions — workspace snapshots and the
 *  documents the agent authored, merged chronologically, with the live head overlaid on the
 *  newest snapshot (or appended standalone when there are none). The last entry is the
 *  latest. Versions are conversation-scoped (the snapshots + documents lists); the message
 *  blocks only carry the live head and the inline chips that open a version here. */
export function collectViewItems(
  messages: ChatMessage[],
  snapshots: ViewSnapshotRef[] = [],
  documents: ViewDocumentRef[] = [],
): ViewItem[] {
  let live: ViewLiveRef | null = null;
  for (const m of messages)
    for (const b of m.blocks ?? []) if (b.kind === "view_live") live = b.live;

  const items: ViewItem[] = snapshots.map((s) => ({
    key: snapshotKey(s.snapshotId),
    label: "",
    isLatest: false,
    snapshot: s,
  }));

  // One entry per committed document version (version ≥ 1); snapshots and document
  // versions share this one ordered list.
  for (const d of documents)
    if (d.version >= 1)
      items.push({
        key: documentKey(d.documentId, d.version),
        label: "",
        isLatest: false,
        document: d,
      });

  // Merge snapshots and document versions into one chronological timeline (by mint time),
  // so "latest" and the inline-edit affordance land on the genuinely newest version — not
  // whichever kind happened to be appended last.
  items.sort(
    (a, b) => Date.parse(itemCreatedAt(a)) - Date.parse(itemCreatedAt(b)),
  );

  // live = the latest snapshot: overlay the running server on the newest snapshot
  // entry, so its preview is the live iframe while its code stays that snapshot's
  // files. With no snapshots, the live head stands alone as the (latest) entry.
  if (live) {
    const lastSnap = [...items].reverse().find((i) => i.snapshot);
    if (lastSnap) lastSnap.live = live;
    else items.push({ key: LIVE_KEY, label: "", isLatest: false, live });
  }

  // An in-progress document (version 0, still streaming its `document.delta`) is a
  // live head: overlay its streaming body onto that document's newest committed
  // entry (so its preview updates live while its key stays stable), or stand it
  // alone as the latest entry when the document has no committed version yet.
  const pending = documents.find((d) => d.version === 0);
  if (pending) {
    const lastDoc = [...items]
      .reverse()
      .find((i) => i.document?.documentId === pending.documentId);
    if (lastDoc) lastDoc.document = pending;
    else
      items.push({
        key: documentKey(pending.documentId, 0),
        label: "",
        isLatest: false,
        document: pending,
      });
  }

  if (items.length === 0) return items;
  items[items.length - 1].isLatest = true;
  items.forEach((item, i) => {
    item.label = entryLabel(item, i + 1, item.isLatest);
  });
  return items;
}

/** A prior version a snapshot's CODE can be diffed against. */
export interface PriorVersion {
  id: string;
  label: string;
}

/** The snapshots that precede the entry with `key` in the version list, oldest →
 *  newest — the candidates its CODE view can diff against (the last is the immediate
 *  previous). Only snapshot entries have a tree to diff, so a standalone live head
 *  (no captured version) yields none. */
export function priorSnapshots(items: ViewItem[], key: string): PriorVersion[] {
  const out: PriorVersion[] = [];
  for (const item of items) {
    if (item.key === key) break;
    if (item.snapshot)
      out.push({ id: item.snapshot.snapshotId, label: item.label });
  }
  return out;
}

/** The committed versions of the same document that precede the entry with `key`,
 *  oldest → newest — the candidates its CODE view diffs against (client-side, from
 *  the bodies already in hand; the last is the immediate previous version). */
export function priorDocumentVersions(
  items: ViewItem[],
  key: string,
): ViewDocumentRef[] {
  const target = items.find((i) => i.key === key)?.document;
  if (!target) return [];
  const out: ViewDocumentRef[] = [];
  for (const item of items) {
    if (item.key === key) break;
    if (
      item.document?.documentId === target.documentId &&
      item.document.version >= 1
    )
      out.push(item.document);
  }
  return out;
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
