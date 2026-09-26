import { createResource, Show, type JSX } from "solid-js";
import { Segmented, toast } from "~/ui";
import { fetchAutoCompactOverride, setAutoCompactOverride } from "../data";
import { settled } from "~/lib/resource";
import { StatRow } from "./StatRow";

const HINT =
  "When this conversation nears the model's context limit, fold its earlier turns into a summary and keep going. The full transcript stays here — only what the model re-reads is condensed.";

/** The three choices, keyed by a string because a radiogroup's value is one. `default`
 *  is the absence of a pin — the thread inherits the global setting. */
type Choice = "on" | "off" | "default";
const TO_OVERRIDE: Record<Choice, boolean | null> = {
  on: true,
  off: false,
  default: null,
};
const toChoice = (override: boolean | null): Choice =>
  override === null ? "default" : override ? "on" : "off";

/** The per-conversation auto-compaction control, as one row of the conversation's
 *  stats panel: the effective state as the row's value, and three choices that pin the
 *  behaviour for *this* conversation or clear the pin so it inherits the global
 *  default. The backend owns the resolution; this only reflects and relays it. Renders
 *  nothing until a thread exists.
 *
 *  It has been a `Toggle` plus a reset `Button` (in the band above the transcript), then
 *  a `Fold on` word opening a menu (in the readout line under the composer). In the panel
 *  the three choices can simply be shown: the panel is already the thing the operator
 *  opened, and a menu inside it would be a click to reach a click. "Use the default" as
 *  the third segment keeps what the menu fixed about the switch — the reset is not a
 *  second control to notice, it is one of the options. */
export function ConversationCompactionToggle(props: {
  conversationId: () => string | null;
}): JSX.Element {
  // Tag the fetched state with its conversation, so a thread switch can't show the previous
  // thread's value (or write against the wrong conversation) before the refetch lands.
  //
  // The fetcher swallows its own failure rather than rejecting, for the same reason
  // `ConversationGrants` does: this row is a secondary read in a portalled panel, which
  // sits *outside* the transcript's ErrorBoundary. A rejected resource re-throws on read
  // (Solid's `.latest` calls `read()` while unresolved) and would blank the whole chat
  // screen over an unreachable toggle endpoint. Losing the row until the next thread
  // switch is the right cost.
  const [state, { mutate }] = createResource(
    () => props.conversationId(),
    async (id) => {
      const s = await fetchAutoCompactOverride(id).catch(() => null);
      return s ? { id, ...s } : null;
    },
  );
  // `settled`, not the resource — reading it while pending would suspend the
  // content region on every thread switch.
  const current = () => {
    const s = settled(state);
    return s && s.id === props.conversationId() ? s : undefined;
  };

  // `true`/`false` pin a per-chat override; `null` clears it back to inheriting the global default.
  async function apply(next: boolean | null) {
    const id = props.conversationId();
    if (!id) return;
    try {
      const saved = await setAutoCompactOverride(id, next);
      mutate({ id, ...saved });
    } catch {
      toast.error("Unable to update auto-compaction for this chat.");
    }
  }

  return (
    <Show when={current()}>
      {(s) => (
        <StatRow
          label="Auto-compaction"
          // The value says whether a pin is doing it, because "on" means two different
          // things: this thread asked for it, or it is simply what every thread does.
          value={`${s().effective ? "On" : "Off"}${s().override === null ? " (default)" : ""}`}
          hint={HINT}
        >
          <Segmented
            aria-label="Auto-compaction for this conversation"
            value={toChoice(s().override)}
            onChange={(choice) => void apply(TO_OVERRIDE[choice])}
            options={[
              { value: "on", label: "On" },
              { value: "off", label: "Off" },
              {
                value: "default",
                label: "Default",
                description: "Inherit the global setting from Settings → Chat.",
              },
            ]}
          />
        </StatRow>
      )}
    </Show>
  );
}
