import { Show, createEffect, createSignal, onMount, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
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

export interface ComposerProps {
  onSend: (text: string) => void;
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
  class?: string;
}

/**
 * Message input. Enter sends; Shift+Enter inserts a newline. Drafts auto-save to
 * localStorage (per `storageKey`) and restore on return, so an interrupted or
 * resumed message is never lost. Cosmetic difference between the docked bar and
 * the hero field is the `size` prop — never a forked component.
 */
export function Composer(props: ComposerProps): JSX.Element {
  const [text, setText] = createSignal("");
  let field: HTMLTextAreaElement | undefined;

  // Load the draft for the active key (also runs on mount, and on key change).
  createEffect(() => {
    const key = props.storageKey;
    setText(key ? loadDraft(key) : "");
  });

  // Persist edits back to the active key.
  createEffect(() => {
    const key = props.storageKey;
    if (!key) return;
    saveDraft(key, text());
  });

  onMount(() => {
    if (props.autofocus) field?.focus();
  });

  const submit = () => {
    const value = text().trim();
    if (!value || props.disabled) return;
    props.onSend(value);
    setText(""); // clears the persisted draft via the effect above
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

  // While a run streams, the primary action interrupts rather than sends — the
  // STOP button stays clickable even though the field is disabled mid-stream.
  const actionBtn = (
    <Show
      when={props.streaming}
      fallback={
        <Button
          variant="primary"
          trailing="send"
          disabled={props.disabled || !text().trim()}
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

  return (
    <Show
      when={lg()}
      fallback={
        <div class={cx("border-t border-line bg-surface p-3", props.class)}>
          <div class="flex items-end gap-2">
            {textarea}
            <Show when={props.controls}>{props.controls}</Show>
            {actionBtn}
          </div>
        </div>
      }
    >
      <div
        class={cx(
          "flex flex-col gap-3 border-2 border-line bg-surface p-4 transition-colors focus-within:border-bright",
          props.class,
        )}
      >
        <Show when={props.title}>
          <Text variant="label" tone="dim">
            {props.title}
          </Text>
        </Show>
        {textarea}
        <div class="flex items-center justify-between gap-2">
          <Show when={props.controls} fallback={<span />}>
            {props.controls}
          </Show>
          {actionBtn}
        </div>
      </div>
    </Show>
  );
}
