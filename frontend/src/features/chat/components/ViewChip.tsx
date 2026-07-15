import { Show, type JSX } from "solid-js";
import { Icon, StatusFlag, Text, cx, type IconName } from "~/ui";
import { detectContentKind, type ViewItem } from "../viewport";

/** Fallback kind word derived from `icon` alone, for callers that only have a
 *  chip icon (no full `ViewItem`) — e.g. the transcript's inline chips, which
 *  reference a version/document/live block, not the consolidated View list. */
const ICON_WORD: Partial<Record<IconName, string>> = {
  play: "LIVE",
  image: "IMAGE",
  eye: "SNAPSHOT",
  file: "FILE",
};

/** A coarse glyph + short kind word for a View item, so a chip/cell states what
 *  it opens before the click. Live overlays a snapshot's preview but still reads
 *  "LIVE" (the running server); a document reads "DOC"; a snapshot whose stamped
 *  preview is an image reads "IMAGE"; anything else reads "SNAPSHOT". */
export function classifyViewItem(item: ViewItem): {
  icon: IconName;
  word: string;
} {
  if (item.live) return { icon: "play", word: "LIVE" };
  if (item.document) return { icon: "file", word: "DOC" };
  const kind = detectContentKind(null, item.snapshot?.preview?.kind ?? null);
  if (kind === "image") return { icon: "image", word: "IMAGE" };
  return { icon: "eye", word: "SNAPSHOT" };
}

/** The `V{n}` version label baked into `item.label` by `collectViewItems`
 *  (every entry gets one, regardless of kind) — reused here rather than
 *  re-deriving the item's position. */
export function viewItemVersionLabel(item: ViewItem): string | undefined {
  const m = /^V(\d+)/.exec(item.label);
  return m ? `V${m[1]}` : undefined;
}

/** `HH:MM` (operator-local) the item was minted, when its snapshot/document
 *  carries a `createdAt` — absent for a standalone live head. */
export function viewItemTimeLabel(item: ViewItem): string | undefined {
  const iso = item.snapshot?.createdAt ?? item.document?.createdAt;
  if (!iso) return undefined;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return undefined;
  const p = (n: number) => n.toString().padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}`;
}

/**
 * A compact, clickable marker in the transcript for something the agent put in the
 * conversation's View — a snapshot version, a document version, or the live head.
 * Clicking opens it in the viewport, so the transcript stays a readable narrative
 * while the heavy render lives beside it (and older versions stay reachable from
 * where they happened). States what it opens before the click: a kind glyph + a
 * short kind word, the title, and a trailing version/time.
 */
export function ViewChip(props: {
  icon: IconName;
  label: string;
  live?: boolean;
  onOpen: () => void;
  /** Short kind word before the title (SNAPSHOT / DOC / LIVE / IMAGE / …). Falls
   *  back to a word derived from `icon` when the caller has no richer `ViewItem`
   *  to classify. */
  kindWord?: string;
  /** Trailing meta — a version label ("V3") or an HH:MM time. */
  meta?: string;
  /** Dims + tags the chip NEW — an unseen item (index >= the operator's seen
   *  count). Monochrome brightness only, never a color. */
  isNew?: boolean;
}): JSX.Element {
  const kindWord = () => props.kindWord ?? ICON_WORD[props.icon] ?? "VIEW";
  return (
    <button
      type="button"
      onClick={() => props.onOpen()}
      class={cx(
        "group/chip flex w-full items-center gap-2 border border-line bg-surface",
        "px-3 py-2 text-left transition-colors hover:border-bright",
        props.isNew && "opacity-80",
      )}
    >
      <Icon
        name={props.icon}
        size={14}
        class="shrink-0 text-dim transition-colors group-hover/chip:text-text"
      />
      <Text variant="label" tone="default">
        {kindWord()}
      </Text>
      <Text variant="micro" tone="dim" class="min-w-0 flex-1 truncate">
        {props.label}
      </Text>
      <Show when={props.meta}>
        <Text variant="micro" tone="dim">
          {props.meta}
        </Text>
      </Show>
      <Show when={props.isNew}>
        <Text variant="micro" tone="dim" class="tracking-label">
          NEW
        </Text>
      </Show>
      <Show when={props.live}>
        <StatusFlag status="live" dot pulse>
          LIVE
        </StatusFlag>
      </Show>
      <Icon
        name="chevron-right"
        size={14}
        class="shrink-0 text-dim transition-colors group-hover/chip:text-bright"
      />
    </button>
  );
}
