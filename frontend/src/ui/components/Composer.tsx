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
  /** A run is generating: the SEND button becomes a STOP button wired to
   *  `onStop`, so the interrupt control sits where the user's focus already is. */
  streaming?: boolean;
  /** Invoked when STOP is pressed mid-stream (see `streaming`). */
  onStop?: () => void;
  placeholder?: string;
  /** `md` = docked input bar (default); `lg` = centered hero field. */
  size?: "md" | "lg";
  /** Uppercase label shown above the field (hero/`lg` use). */
  title?: string;
  autofocus?: boolean;
  /** Persists the unsent draft to localStorage under this key, reactively —
   *  switching keys (e.g. between conversations) loads that key's draft. */
  storageKey?: string;
  /** Inline controls placed in the action row, e.g. a model selector. */
  controls?: JSX.Element;
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

  const fieldClass = () =>
    cx(
      "w-full resize-none font-mono text-bright placeholder:text-dim outline-none transition-colors disabled:opacity-40",
      lg()
        ? "min-h-20 bg-transparent border-0 px-1 py-1 text-body"
        : "min-h-8 flex-1 bg-bg border border-line rounded-ctl px-2 py-1.5 text-body focus:border-bright",
    );

  const textarea = (
    <textarea
      ref={field}
      value={text()}
      onInput={(e) => setText(e.currentTarget.value)}
      onKeyDown={onKeyDown}
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
        size={lg() ? "md" : "sm"}
        leading="upload"
        aria-label="Attach files"
        disabled={props.disabled}
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

  // While a run streams, the primary action interrupts rather than sends — the
  // STOP button stays clickable even though the field is disabled mid-stream.
  const actionBtn = (
    <Show
      when={props.streaming}
      fallback={
        <Button
          variant="primary"
          trailing="send"
          disabled={!canSend()}
          onClick={submit}
        >
          SEND
        </Button>
      }
    >
      <Button variant="default" leading="stop" onClick={() => props.onStop?.()}>
        STOP
      </Button>
    </Show>
  );

  // A subtle full-surface highlight while files hover the composer, so the drop
  // target reads clearly without a separate dashed zone.
  const dropOverlay = (
    <Show when={props.attachments && drop.isDragging()}>
      <div class="pointer-events-none absolute inset-0 z-10 flex items-center justify-center border-2 border-dashed border-info bg-info/10">
        <Text variant="label" tone="info">
          <span class="inline-flex items-center gap-2">
            <Icon name="upload" size={16} />
            DROP TO ATTACH
          </span>
        </Text>
      </div>
    </Show>
  );

  return (
    <Show
      when={lg()}
      fallback={
        <div
          class={cx(
            "relative border-t border-line bg-surface p-3",
            props.class,
          )}
          {...(props.attachments ? drop.dropHandlers : {})}
        >
          {dropOverlay}
          {chips}
          <div class="flex items-end gap-2">
            {attachBtn}
            {textarea}
            <Show when={props.controls}>{props.controls}</Show>
            {actionBtn}
          </div>
        </div>
      }
    >
      <div
        class={cx(
          "relative flex flex-col gap-3 border-2 border-line bg-surface p-4 transition-colors focus-within:border-bright",
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
          <div class="flex items-center gap-2">
            {attachBtn}
            <Show when={props.controls}>{props.controls}</Show>
          </div>
          {actionBtn}
        </div>
      </div>
    </Show>
  );
}
