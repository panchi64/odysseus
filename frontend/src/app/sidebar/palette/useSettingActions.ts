import { createSignal, type Accessor } from "solid-js";
import { toast } from "~/ui";
import { createInFlight } from "~/lib/inFlight";
import {
  nextChoiceValue,
  parseSettingNumber,
  type SettingEntry,
} from "~/app/nav";

export interface SettingActions {
  /** The id of the setting whose inline number field is open, or null. */
  editing: Accessor<string | null>;
  /** Whether this row's write is in flight — asked per row, because the answer is
   *  per row even though only one write runs at a time. */
  busy: (id: string) => boolean;
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
  // racing two writes against the same seam. That was the intent all along, but a
  // single id slot never enforced it — a second activation simply overwrote the slot,
  // and then whichever write finished first cleared it, undimming a row whose value
  // was still in the air and letting it assert a state nothing had confirmed. So the
  // refusal is real now: while any write is running, the next activation does nothing
  // and the row it came from doesn't move.
  const writes = createInFlight<string>();
  let field: HTMLInputElement | undefined;

  const cancel = (): void => {
    setEditing(null);
  };

  const write = (
    entry: SettingEntry,
    run: () => void | Promise<void>,
  ): void => {
    if (writes.any()) return;
    void writes.run(entry.id, async () => {
      try {
        await run();
      } catch {
        // The seam relays; the backend decides. All this can say is that it didn't
        // take — the row re-reads and keeps showing the state that actually holds.
        toast.error(`Unable to change ${entry.label}.`);
      }
    });
  };

  const activate = (entry: SettingEntry): void => {
    switch (entry.kind) {
      case "toggle": {
        // A row whose seam hasn't loaded reads "—" and has no state to invert:
        // defaulting to `false` would write `true` regardless of what actually
        // holds, from a row that never showed the operator a value to change.
        const current = entry.read();
        if (current === undefined) return;
        write(entry, () => entry.write(!current));
        return;
      }
      case "choice": {
        const next = nextChoiceValue(entry.options, entry.read());
        if (next !== undefined) write(entry, () => entry.write(next));
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
    write(entry, () => entry.write(parsed));
  };

  return {
    editing,
    busy: writes.has,
    draft,
    setDraft,
    setField: (el) => (field = el),
    activate,
    commit,
    cancel,
  };
}
