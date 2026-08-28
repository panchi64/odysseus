import { createSignal, type Accessor } from "solid-js";
import { toast } from "~/ui";
import {
  nextChoiceValue,
  parseSettingNumber,
  type SettingEntry,
} from "~/app/nav";

export interface SettingActions {
  /** The id of the setting whose inline number field is open, or null. */
  editing: Accessor<string | null>;
  /** The id of the setting whose write is in flight, or null. */
  busy: Accessor<string | null>;
  draft: Accessor<string>;
  setDraft: (value: string) => void;
  /** Register the inline field so opening one can focus it. */
  setField: (el: HTMLInputElement) => void;
  /** Flip a toggle, cycle a choice, or open a number's inline field. */
  activate: (entry: SettingEntry) => void;
  /** Parse and save the open field; a rejected value stays put with a toast. */
  commit: (entry: SettingEntry) => void;
  /** Abandon the open field without saving. */
  cancel: () => void;
}

/**
 * Changing a setting from the palette: the write, its in-flight and error
 * handling, and the one piece of transient UI a number needs (an inline field
 * with a draft). Extracted so the palette body is left holding query, cursor,
 * keys, and layout — the two concerns have nothing to say to each other beyond
 * "the operator activated this row".
 *
 * Every write goes through the entry's own `write`, which is the feature seam's
 * action. Nothing here decides whether a value is allowed; the number parse is
 * immediate feedback on an obvious typo, and the backend re-validates regardless.
 */
export function useSettingActions(): SettingActions {
  const [editing, setEditing] = createSignal<string | null>(null);
  const [draft, setDraft] = createSignal("");
  // One at a time: activation is a keystroke, and there is nothing to gain from
  // racing two writes against the same seam.
  const [busy, setBusy] = createSignal<string | null>(null);
  let field: HTMLInputElement | undefined;

  const cancel = (): void => {
    setEditing(null);
  };

  const write = async (
    entry: SettingEntry,
    run: () => void | Promise<void>,
  ): Promise<void> => {
    setBusy(entry.id);
    try {
      await run();
    } catch {
      // The seam relays; the backend decides. All this can say is that it didn't
      // take — the row re-reads and keeps showing the state that actually holds.
      toast.error(`Unable to change ${entry.label}.`);
    } finally {
      setBusy(null);
    }
  };

  const activate = (entry: SettingEntry): void => {
    switch (entry.kind) {
      case "toggle": {
        // A row whose seam hasn't loaded reads "—" and has no state to invert:
        // defaulting to `false` would write `true` regardless of what actually
        // holds, from a row that never showed the operator a value to change.
        const current = entry.read();
        if (current === undefined) return;
        void write(entry, () => entry.write(!current));
        return;
      }
      case "choice": {
        const next = nextChoiceValue(entry.options, entry.read());
        if (next !== undefined) void write(entry, () => entry.write(next));
        return;
      }
      case "number":
        // Seeded from the live value, so Enter-then-Enter is a no-op rather than
        // a blank field that would parse to nothing.
        setDraft(String(entry.read() ?? ""));
        setEditing(entry.id);
        queueMicrotask(() => field?.focus());
    }
  };

  const commit = (entry: SettingEntry): void => {
    if (entry.kind !== "number") return;
    const parsed = parseSettingNumber(entry, draft());
    if (parsed === null) {
      const range =
        entry.min !== undefined && entry.max !== undefined
          ? ` between ${entry.min} and ${entry.max}`
          : entry.min !== undefined
            ? ` of ${entry.min} or more`
            : "";
      toast.error(`Enter a whole number${range}.`);
      return;
    }
    cancel();
    void write(entry, () => entry.write(parsed));
  };

  return {
    editing,
    busy,
    draft,
    setDraft,
    setField: (el) => (field = el),
    activate,
    commit,
    cancel,
  };
}
