import { createResource, Show, type JSX } from "solid-js";
import { Button, Text, Toggle, Tooltip, toast } from "~/ui";
import { fetchAutoCompactOverride, setAutoCompactOverride } from "../data";

const TOOLTIP =
  "When this conversation nears the model's context limit, fold its earlier turns into a summary and keep going. The full transcript stays here — only what the model re-reads is condensed.";
const RESET_TOOLTIP =
  "This chat overrides the global auto-compaction default. Clear it to inherit the default again.";

/** A compact per-conversation auto-compaction switch for the conversation status strip:
 *  a FOLD label and a mechanical toggle showing the thread's effective state. Flipping it
 *  forces the behaviour on/off for *this* conversation, overriding the global default.
 *  When the thread carries an explicit override a reset control appears so it can fall
 *  back to inheriting that default (otherwise a once-flipped thread would ignore later
 *  changes to it). The backend owns the resolution; this only reflects + relays it.
 *  Renders nothing until a thread exists. */
export function ConversationCompactionToggle(props: {
  conversationId: () => string | null;
}): JSX.Element {
  // Tag the fetched state with its conversation, so a thread switch can't show the previous
  // thread's value (or write a toggle against the wrong conversation) before the refetch lands.
  //
  // The fetcher swallows its own failure rather than rejecting, for the same reason
  // `ConversationGrants` does: this switch is a secondary read in the conversation
  // status strip, which sits *outside* the transcript's ErrorBoundary. A rejected
  // resource re-throws on read (Solid's `.latest` calls `read()` while unresolved) and
  // would blank the whole chat screen over an unreachable toggle endpoint. Losing the
  // switch until the next thread switch is the right cost.
  const [state, { mutate }] = createResource(
    () => props.conversationId(),
    async (id) => {
      const s = await fetchAutoCompactOverride(id).catch(() => null);
      return s ? { id, ...s } : null;
    },
  );
  // `.latest`, not the resource — reading it while pending would suspend the
  // content region on every thread switch.
  const current = () => {
    const s = state.latest;
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
        <span class="flex items-center gap-1.5">
          <Tooltip label={TOOLTIP} side="bottom" float>
            <span class="flex items-center gap-1.5">
              <Text
                variant="label"
                tone={s().override === null ? "dim" : "bright"}
              >
                Fold
              </Text>
              <Toggle checked={s().effective} onChange={(v) => void apply(v)} />
            </span>
          </Tooltip>
          <Show when={s().override !== null}>
            <Tooltip label={RESET_TOOLTIP} side="bottom" float>
              <Button
                variant="ghost"
                size="sm"
                leading="refresh"
                aria-label="Inherit the global auto-compaction default"
                onClick={() => void apply(null)}
              />
            </Tooltip>
          </Show>
        </span>
      )}
    </Show>
  );
}
