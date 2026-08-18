import { createSignal, Show, type JSX } from "solid-js";
import { Disclosure, Input, Row, Select, Stack, Text } from "~/ui";
import type { EngineKind } from "~/lib/api/models-types";
import type { KvCacheType, LaunchOptions } from "../model";

/** The blank slate: every field unset, so the engine's own defaults stand. */
export const EMPTY_OPTIONS: LaunchOptions = {
  contextSize: null,
  kvCacheType: null,
  cacheReuse: null,
  extraArgs: [],
};

const KV_CACHE_OPTIONS = [
  { value: "", label: "Engine default (f16)" },
  { value: "q8_0", label: "q8_0 — half the cache, near-identical output" },
  { value: "q4_0", label: "q4_0 — quarter the cache, some quality cost" },
];

/** A number typed into a text field: blank stays unset rather than becoming 0, since
 *  an unset field must emit no flag at all. Non-integers are rejected too — both fields
 *  are token counts, and a `1.5` would only reach the backend to be refused there. */
function toNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
}

/** Whether the operator left every field alone, so the serve request can omit the
 *  options entirely and keep whatever the model was last tuned with. */
export function hasAnyOption(o: LaunchOptions): boolean {
  return (
    o.contextSize != null ||
    o.kvCacheType != null ||
    o.cacheReuse != null ||
    o.extraArgs.length > 0
  );
}

/**
 * Engine tuning for one model, collapsed by default.
 *
 * Only knobs that are genuinely off in the engine appear as fields — llama.cpp already
 * auto-sizes server slots, GPU layers, flash attention, continuous batching and prompt
 * caching, so surfacing those would invite an operator to replace good sizing with a
 * guess. Everything unanticipated goes through EXTRA ARGUMENTS instead, and the backend
 * rejects any argument that collides with a field here.
 */
export function AdvancedServeOptions(props: {
  engine: EngineKind | null;
  value: LaunchOptions;
  onChange: (next: LaunchOptions) => void;
}): JSX.Element {
  const patch = (part: Partial<LaunchOptions>): void =>
    props.onChange({ ...props.value, ...part });

  // The argument field keeps its own raw text. Feeding the parsed array back through
  // `join(" ")` would swallow the space the operator just typed, so a second argument
  // could never be entered.
  const [rawArgs, setRawArgs] = createSignal(props.value.extraArgs.join(" "));
  const onArgsInput = (text: string): void => {
    setRawArgs(text);
    patch({ extraArgs: text.split(/\s+/).filter(Boolean) });
  };

  return (
    // MLX takes none of these — its server has no equivalent flags, so offering them
    // would be offering settings that silently do nothing.
    <Show when={props.engine === "llama.cpp"}>
      <Disclosure label="ADVANCED">
        <Stack gap={3}>
          <Text variant="micro" tone="dim">
            Leave these blank unless you have a reason. The engine sizes its own
            slots, GPU layers and batching, and blank means it keeps doing so.
          </Text>
          <Row gap={3} align="end" wrap>
            <div class="min-w-0 flex-1">
              <Input
                label="CONTEXT SIZE"
                type="number"
                inputMode="numeric"
                min="0"
                placeholder="auto"
                value={props.value.contextSize ?? ""}
                onInput={(e) =>
                  patch({ contextSize: toNumber(e.currentTarget.value) })
                }
                hint="Tokens across all slots. Blank uses the model's own declared window, which can be far larger than your memory holds."
              />
            </div>
            <div class="min-w-0 flex-1">
              <Input
                label="CACHE REUSE"
                type="number"
                inputMode="numeric"
                min="0"
                placeholder="0"
                value={props.value.cacheReuse ?? ""}
                onInput={(e) =>
                  patch({ cacheReuse: toNumber(e.currentTarget.value) })
                }
                hint="Smallest prompt chunk the engine will reuse from cache. Off by default."
              />
            </div>
          </Row>
          <Select
            label="KV CACHE TYPE"
            options={KV_CACHE_OPTIONS}
            value={props.value.kvCacheType ?? ""}
            onChange={(v) =>
              patch({ kvCacheType: (v || null) as KvCacheType | null })
            }
            hint="Quantizing the cache buys back the memory a long context eats."
          />
          <Input
            label="EXTRA ARGUMENTS"
            placeholder="--cache-ram 16384"
            value={rawArgs()}
            onInput={(e) => onArgsInput(e.currentTarget.value)}
            hint="Passed to the engine verbatim and unsupported — you own whatever you set here."
          />
        </Stack>
      </Disclosure>
    </Show>
  );
}
