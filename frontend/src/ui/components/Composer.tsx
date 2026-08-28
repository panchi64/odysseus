import {
  For,
  Show,
  createEffect,
  createSignal,
  untrack,
  type Accessor,
  type JSX,
} from "solid-js";
import { cx } from "../cx";
import { Icon } from "../primitives/Icon";
import { Text } from "../primitives/Text";
import { HIDDEN_FILE_INPUT, useFileDrop } from "../primitives/useFileDrop";
import { AttachmentChip, type ComposerAttachment } from "./AttachmentChip";
import { Button } from "./Button";

// Self-contained guarded storage: the design system does not depend on ~/lib, so
// the Composer keeps its own best-effort draft persistence rather than importing
// the app's storage helper.
const DRAFT_PREFIX = "ody.draft.";

// The docked field grows with its content up to this many lines, then scrolls —
// long prompts stay readable without the bar swallowing the conversation.
const MAX_ROWS = 6;

function loadDraft(key?: string): string {
  if (!key) return "";
  try {
    return localStorage.getItem(DRAFT_PREFIX + key) ?? "";
  } catch {
    return "";
  }
}

function saveDraft(key: string, value: string): void {
  try {
    if (value) localStorage.setItem(DRAFT_PREFIX + key, value);
    else localStorage.removeItem(DRAFT_PREFIX + key);
  } catch {
    /* storage unavailable — drafts are best-effort */
  }
}

/**
 * Attachment controller injected by the feature layer. The design system can't
 * reach the uploads data seam, so the Composer owns the *chips* but not the
 * upload/poll — the feature hands it this. The Composer reads `items` to render,
 * drives `attach`/`remove`/`toggleKbExcluded` from the chip controls, reads the
 * ready ids on SEND, and calls `clear` after a send.
 */
export interface ComposerAttachmentsApi {
  items: Accessor<ComposerAttachment[]>;
  attach: (files: File[]) => void;
  remove: (id: string) => void;
  toggleKbExcluded: (id: string) => void;
  clear: () => void;
}

export interface ComposerProps {
  /** Receives the trimmed text and the ids of every ready attachment. */
  onSend: (text: string, attachmentIds: string[]) => void;
  disabled?: boolean;
  /** A run is generating: a STOP button wired to `onStop` joins the action row,
   *  so the interrupt control sits where the user's focus already is. When the
   *  field itself stays enabled (`disabled` false), SEND remains beside it —
   *  the caller queues the message into the live run (mid-run steering); a
   *  disabled field shows STOP alone. Attaching is unavailable while streaming
   *  either way. */
  streaming?: boolean;
  /** Invoked when STOP is pressed mid-stream (see `streaming`). */
  onStop?: () => void;
  /** Text to insert into the field programmatically (e.g. an undelivered queued
   *  message restored after a cancel). Applied whenever it becomes non-empty —
   *  appended below any current draft — then acknowledged via
   *  `onPrefillConsumed` so the caller can clear it. */
  prefill?: string | null;
  onPrefillConsumed?: () => void;
  placeholder?: string;
  /** `md` = docked input bar (default); `lg` = centered hero field. */
  size?: "md" | "lg";
  /** Sentence-case label shown above the field (hero/`lg` use). */
  title?: string;
  autofocus?: boolean;
  /** Persists the unsent draft to localStorage under this key, reactively —
   *  switching keys (e.g. between conversations) loads that key's draft. */
  storageKey?: string;
  /** Inline controls placed in the action row, e.g. a model selector. */
  controls?: JSX.Element;
  /** Drop the surface fill — **the bloom is kept**. The field and its action row
   *  sit directly on whatever is behind them, with the aura still marking them
   *  as the point of action.
   *
   *  For a composer that sits inside another surface (the research intake, in a
   *  `Panel`): a fill on a fill is the box-in-a-box §7 exists to stop, and it
   *  reads as a grey slab. The bloom is not part of that problem — it is light,
   *  not a surface, and it is the thing that says "type here". */
  bare?: boolean;
  /** File-attachment controller. When supplied, the Composer shows an attach
   *  button + drag-drop and renders the attachment chips; omit to hide them. */
  attachments?: ComposerAttachmentsApi;
  class?: string;
}

/**
 * Message input. Enter sends; Shift+Enter inserts a newline. Drafts auto-save to
 * localStorage (per `storageKey`) and restore on return, so an interrupted or
 * resumed message is never lost. Cosmetic difference between the docked bar and
 * the hero field is the `size` prop — never a forked component. When an
 * `attachments` controller is supplied, files can be attached (drop or pick) and
 * ride along with the message; a send needs either text or ≥1 ready attachment.
 */
export function Composer(props: ComposerProps): JSX.Element {
  const [text, setText] = createSignal("");
  let field: HTMLTextAreaElement | undefined;

  const items = () => props.attachments?.items() ?? [];
  const readyIds = () =>
    items()
      .filter((a) => a.status === "ready")
      .map((a) => a.id);
  const hasReady = () => readyIds().length > 0;

  const drop = useFileDrop((files) => props.attachments?.attach(files));

  // Load the draft for the active key — runs on mount and whenever the key
  // changes (e.g. switching conversations). This effect is the sole owner of
  // key transitions: it swaps `text` to the incoming key's draft.
  createEffect(() => {
    const key = props.storageKey;
    setText(key ? loadDraft(key) : "");
  });

  // Persist edits back to the active key. Tracks only `text` — the key is read
  // untracked so a key change never writes the outgoing draft under the incoming
  // key (the load effect above already swapped `text`). Tracking the key here
  // would race that load and leak a stale draft across conversations.
  createEffect(() => {
    const value = text();
    const key = untrack(() => props.storageKey);
    if (key) saveDraft(key, value);
  });

  // Focus the field on mount and again whenever the active conversation changes
  // (the key transition), so a freshly opened or newly started chat is ready to
  // type into without a click. Reading `storageKey` tracked makes the refocus
  // fire on switch; `autofocus` is read untracked so only opted-in callers grab
  // focus and a key change alone never enables it.
  createEffect(() => {
    // Returned (rather than discarded) so reading the key counts as a tracked
    // dependency — the refocus then fires on every conversation switch.
    const key = props.storageKey;
    if (untrack(() => props.autofocus)) field?.focus();
    return key;
  });

  // Re-focus when the field re-enables after a run finishes (disabled true →
  // false), so the conversation continues without a click. Gated on `autofocus`
  // — same opt-in as the mount/switch focus above — and only on the enabling
  // edge, so an idle field toggling for any other reason doesn't grab focus.
  let wasDisabled = untrack(() => props.disabled) ?? false;
  createEffect(() => {
    const disabled = props.disabled ?? false;
    if (wasDisabled && !disabled && untrack(() => props.autofocus))
      field?.focus();
    wasDisabled = disabled;
  });

  // Apply a caller-provided prefill (restored undelivered text): append below
  // any current draft, hand focus back, and acknowledge so the caller clears it.
  createEffect(() => {
    const incoming = props.prefill;
    if (!incoming) return;
    setText((current) => (current ? `${current}\n${incoming}` : incoming));
    props.onPrefillConsumed?.();
    field?.focus();
  });

  const canSend = () =>
    !props.disabled && (Boolean(text().trim()) || hasReady());

  const submit = () => {
    if (!canSend()) return;
    props.onSend(text().trim(), readyIds());
    setText(""); // clears the persisted draft via the effect above
    props.attachments?.clear();
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const lg = () => props.size === "lg";

  // Grow the docked field to fit its content, capped at MAX_ROWS (then scroll).
  // The hero (`lg`) variant keeps its fixed rows. Runs on every text change —
  // typing, draft load, and clear-after-send all reflow the height.
  const autosize = () => {
    const el = field;
    if (!el || lg()) return;
    el.style.height = "auto";
    const cs = getComputedStyle(el);
    const line = parseFloat(cs.lineHeight) || 20;
    const padding = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    const border =
      parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth);
    const max = line * MAX_ROWS + padding + border;
    // `scrollHeight` covers content + padding but not border; the field is
    // border-box, so add the border back or the set height clips by that much.
    const fit = el.scrollHeight + border;
    el.style.height = `${Math.min(fit, max)}px`;
    el.style.overflowY = fit > max ? "auto" : "hidden";
  };
  createEffect(() => {
    text(); // reflow whenever the value changes
    autosize();
  });

  /* The field carries no chrome of its own — no border, no fill, no focus ring.
     The card around it is the control, and it is what lights up on focus, so a
     second bordered box inside it would only add a line (§7). */
  const fieldClass = () =>
    cx(
      "w-full resize-none border-0 bg-transparent px-1 py-1 text-body font-sans text-bright placeholder:text-dim outline-none disabled:opacity-40",
      lg() ? "min-h-20" : "min-h-8",
    );

  const textarea = (
    <textarea
      ref={field}
      value={text()}
      onInput={(e) => setText(e.currentTarget.value)}
      onKeyDown={onKeyDown}
      onPaste={props.attachments ? drop.pasteHandlers.onPaste : undefined}
      rows={lg() ? 3 : 1}
      placeholder={props.placeholder ?? "Message the agent…"}
      disabled={props.disabled}
      class={fieldClass()}
    />
  );

  // The attach affordance: a button that opens the picker plus the hidden input
  // the file-drop hook clicks. Only mounted when an attachments controller is
  // wired, so non-attachment surfaces are unchanged.
  const attachBtn = (
    <Show when={props.attachments}>
      <Button
        variant="ghost"
        size={lg() ? "lg" : "md"}
        leading="upload"
        iconSize={lg() ? 28 : 22}
        aria-label="Attach files"
        disabled={props.disabled || props.streaming}
        onClick={drop.openPicker}
      />
      <input
        ref={drop.bindInput}
        {...HIDDEN_FILE_INPUT}
        {...drop.inputHandlers}
      />
    </Show>
  );

  // Attachment chips, above the field. Each shows status, a KB-membership
  // toggle, and a remove control. The wrapping margin is the docked bar's; the
  // hero stacks it with the field via the column gap.
  const chips = (
    <Show when={props.attachments && items().length > 0}>
      <div class={cx("flex flex-wrap gap-2", !lg() && "mb-2")}>
        <For each={items()}>
          {(a) => (
            <AttachmentChip
              name={a.name}
              status={a.status}
              kbExcluded={a.kbExcluded}
              onToggleKbExcluded={() =>
                props.attachments?.toggleKbExcluded(a.id)
              }
              onRemove={() => props.attachments?.remove(a.id)}
            />
          )}
        </For>
      </div>
    </Show>
  );

  // While a run streams, STOP joins the row so the interrupt sits where the
  // user's focus already is. A caller that keeps the field enabled mid-stream
  // keeps SEND beside it (Enter/SEND then queues into the live run — steering);
  // one that disables the field shows STOP alone, as before.
  const sendBtn = () => (
    <Button
      variant="primary"
      trailing="send"
      disabled={!canSend()}
      onClick={submit}
    >
      Send
    </Button>
  );
  const actionBtn = (
    <Show when={props.streaming} fallback={sendBtn()}>
      <span class="flex items-center gap-2">
        <Show when={!props.disabled}>{sendBtn()}</Show>
        <Button
          variant="default"
          leading="stop"
          onClick={() => props.onStop?.()}
        >
          Stop
        </Button>
      </span>
    </Show>
  );

  // A subtle full-surface highlight while files hover the composer, so the drop
  // target reads clearly without a separate dashed zone.
  const dropOverlay = (
    <Show when={props.attachments && drop.isDragging()}>
      <div class="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-panel border border-dashed border-info bg-info/10">
        <Text variant="label" tone="info">
          <span class="inline-flex items-center gap-2">
            <Icon name="upload" size={16} />
            Drop to attach
          </span>
        </Text>
      </div>
    </Show>
  );

  /* ONE layout for both sizes. The docked bar and the hero used to be separate
     branches — a bordered field nested inside a bordered bar for `md`, a 2px
     box for `lg` — which is exactly the box-in-a-box the system dropped (§7).
     Now both are the same card: a raised surface on smoothed corners, the field
     transparent inside it, and the controls on their own row beneath. Only
     padding and the field's resting height differ.

     The composer is where the operator's attention belongs on these screens, so
     it carries `shadow-bloom` — the wide ambient accent aura (§6.2) — AT REST,
     not on hover or focus. It is not a focus affordance: the composer is the
     point of the screen whether or not the cursor is in it, and a glow that only
     appears once you have already committed to typing is telling you something
     you no longer need to know.

     `shadow-bloom`, not `shadow-accent`: the tight control-sized shadow reads as
     an edge cutout around something this large. */
  return (
    <div
      class={cx(
        "relative flex flex-col gap-2 rounded-panel shadow-bloom",
        !props.bare && "bg-surface",
        lg() ? "p-4" : "p-3",
        props.class,
      )}
      {...(props.attachments ? drop.dropHandlers : {})}
    >
      {dropOverlay}
      <Show when={props.title}>
        <Text variant="label" tone="dim">
          {props.title}
        </Text>
      </Show>
      {chips}
      {textarea}
      <div class="flex items-center justify-between gap-2">
        <div class="flex min-w-0 items-center gap-1">
          {attachBtn}
          <Show when={props.controls}>{props.controls}</Show>
        </div>
        {actionBtn}
      </div>
    </div>
  );
}
