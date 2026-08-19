import { createResource, Show, type JSX } from "solid-js";
import { Button, Text, Toggle, Tooltip, toast } from "~/ui";
import type { CompactionState } from "../model";
import {
  fetchAutoCompactOverride,
  fetchCompactionOverride,
  setAutoCompactOverride,
  setCompactionOverride,
} from "../data";

/** The two context reductions the operator can steer per thread. They condense different
 *  things — `tools` digests individual oversized tool outputs, `turns` folds whole earlier
 *  exchanges into a summary once the context window fills — but the control is identical,
 *  so it is one component with a variant rather than two that drift apart. */
export type CompactionKind = "tools" | "turns";

interface KindConfig {
  label: string;
  tooltip: string;
  resetTooltip: string;
  resetLabel: string;
  error: string;
  fetch: (conversationId: string) => Promise<CompactionState>;
  save: (
    conversationId: string,
    override: boolean | null,
  ) => Promise<CompactionState>;
}

const KINDS: Record<CompactionKind, KindConfig> = {
  tools: {
    label: "CMPCT",
    tooltip:
      "Condense older tool outputs for the model in this conversation. You always keep the full output; the model can expand any digest on demand.",
    resetTooltip:
      "This chat overrides the global compaction default. Clear it to inherit the default again.",
    resetLabel: "Inherit the global compaction default",
    error: "Unable to update compaction for this chat.",
    fetch: fetchCompactionOverride,
    save: setCompactionOverride,
  },
  turns: {
    label: "FOLD",
    tooltip:
      "When this conversation nears the model's context limit, fold its earlier turns into a summary and keep going. The full transcript stays here — only what the model re-reads is condensed.",
    resetTooltip:
      "This chat overrides the global auto-compaction default. Clear it to inherit the default again.",
    resetLabel: "Inherit the global auto-compaction default",
    error: "Unable to update auto-compaction for this chat.",
    fetch: fetchAutoCompactOverride,
    save: setAutoCompactOverride,
  },
};

/** A compact per-conversation compaction switch for the chat header: a short label and a
 *  mechanical toggle showing the thread's effective state. Flipping it forces the behaviour
 *  on/off for *this* conversation, overriding the global default. When the thread carries an
 *  explicit override a reset control appears so it can fall back to inheriting that default
 *  (otherwise a once-flipped thread would ignore later changes to it). The backend owns the
 *  resolution; this only reflects + relays it. Renders nothing until a thread exists. */
export function ConversationCompactionToggle(props: {
  conversationId: () => string | null;
  kind?: CompactionKind;
}): JSX.Element {
  const config = () => KINDS[props.kind ?? "tools"];
  // Tag the fetched state with its conversation, so a thread switch can't show the previous
  // thread's value (or write a toggle against the wrong conversation) before the refetch lands.
  const [state, { mutate }] = createResource(
    () => props.conversationId(),
    async (id) => ({ id, ...(await config().fetch(id)) }),
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
      const saved = await config().save(id, next);
      mutate({ id, ...saved });
    } catch {
      toast.error(config().error);
    }
  }

  return (
    <Show when={current()}>
      {(s) => (
        <span class="flex items-center gap-1.5">
          <Tooltip label={config().tooltip} side="bottom" float>
            <span class="flex items-center gap-1.5">
              <Text
                variant="label"
                tone={s().override === null ? "dim" : "bright"}
              >
                {config().label}
              </Text>
              <Toggle checked={s().effective} onChange={(v) => void apply(v)} />
            </span>
          </Tooltip>
          <Show when={s().override !== null}>
            <Tooltip label={config().resetTooltip} side="bottom" float>
              <Button
                variant="ghost"
                size="sm"
                leading="refresh"
                aria-label={config().resetLabel}
                onClick={() => void apply(null)}
              />
            </Tooltip>
          </Show>
        </span>
      )}
    </Show>
  );
}
