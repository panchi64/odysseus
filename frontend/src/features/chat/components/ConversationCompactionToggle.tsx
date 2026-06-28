import { createResource, Show, type JSX } from "solid-js";
import { Button, Text, Toggle, Tooltip, toast } from "~/ui";
import { fetchCompactionOverride, setCompactionOverride } from "../data";

/** A compact per-conversation compaction switch for the chat header: a `CMPCT` label and a
 *  mechanical toggle showing the thread's effective state. Flipping it forces compaction
 *  on/off for *this* conversation (overriding the global default) — the operator always keeps
 *  the full tool output; only the model's view of older turns is condensed. When the thread
 *  carries an explicit override a reset control appears so it can fall back to inheriting the
 *  global default (otherwise a once-flipped thread would ignore later changes to that default).
 *  The backend owns the resolution; this only reflects + relays it. Renders nothing until a
 *  thread exists. */
export function ConversationCompactionToggle(props: {
  conversationId: () => string | null;
}): JSX.Element {
  // Tag the fetched state with its conversation, so a thread switch can't show the previous
  // thread's value (or write a toggle against the wrong conversation) before the refetch lands.
  const [state, { mutate }] = createResource(
    () => props.conversationId(),
    async (id) => ({ id, ...(await fetchCompactionOverride(id)) }),
  );
  const current = () => {
    const s = state();
    return s && s.id === props.conversationId() ? s : undefined;
  };

  // `true`/`false` pin a per-chat override; `null` clears it back to inheriting the global default.
  async function apply(next: boolean | null) {
    const id = props.conversationId();
    if (!id) return;
    try {
      const saved = await setCompactionOverride(id, next);
      mutate({ id, ...saved });
    } catch {
      toast.error("Unable to update compaction for this chat.");
    }
  }

  return (
    <Show when={current()}>
      {(s) => (
        <span class="flex items-center gap-1.5">
          <Tooltip
            label="Condense older tool outputs for the model in this conversation. You always keep the full output; the model can expand any digest on demand."
            side="bottom"
            float
          >
            <span class="flex items-center gap-1.5">
              <Text
                variant="label"
                tone={s().override === null ? "dim" : "bright"}
              >
                CMPCT
              </Text>
              <Toggle checked={s().effective} onChange={(v) => void apply(v)} />
            </span>
          </Tooltip>
          <Show when={s().override !== null}>
            <Tooltip
              label="This chat overrides the global compaction default. Clear it to inherit the default again."
              side="bottom"
              float
            >
              <Button
                variant="ghost"
                size="sm"
                leading="refresh"
                aria-label="Inherit the global compaction default"
                onClick={() => void apply(null)}
              />
            </Tooltip>
          </Show>
        </span>
      )}
    </Show>
  );
}
