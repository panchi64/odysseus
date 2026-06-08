import { Show, createEffect, createSignal, onMount, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { Button } from "./Button";

const DRAFT_PREFIX = "ody.draft.";

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

  const sendBtn = (
    <Button
      variant="primary"
      trailing="send"
      disabled={props.disabled || !text().trim()}
      onClick={submit}
    >
      SEND
    </Button>
  );

  return (
    <Show
      when={lg()}
      fallback={
        <div class={cx("border-t border-line bg-surface p-3", props.class)}>
          <div class="flex items-end gap-2">
            {textarea}
            <Show when={props.controls}>{props.controls}</Show>
            {sendBtn}
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
          {sendBtn}
        </div>
      </div>
    </Show>
  );
}
