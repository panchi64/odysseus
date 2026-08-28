import { createSignal, Show, type JSX } from "solid-js";
import { Disclosure, Input, Row, Select, Stack, Text } from "~/ui";
import type {
  KvCacheType,
  LaunchOptionField,
  LaunchOptions,
  SpeculativeMode,
} from "../model";

const SPECULATIVE_OPTIONS = [
  { value: "", label: "Auto — on when the weights support it" },
  { value: "off", label: "Off — decode one token at a time" },
];

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

/**
 * Engine tuning for one model, collapsed by default.
 *
 * The fields are engine-neutral: each names something the operator wants, and the
 * backend's adapter translates it into that engine's own flags. Which fields appear is
 * the backend's call too — `supportedOptions` reports what the chosen engine can
 * actually honour, so this never offers a setting that would silently do nothing.
 *
 * Only knobs that are genuinely off in the engine are modelled — the engines already
 * auto-size server slots, GPU layers, flash attention, continuous batching and prompt
 * caching, so surfacing those would invite an operator to replace good sizing with a
 * guess. EXTRA ARGUMENTS is always available for everything else, and doubles as the
 * override: naming a flag one of the fields above would emit replaces it.
 */
export function AdvancedServeOptions(props: {
  /** The LaunchOptions fields the chosen engine honours (from its recommendation). */
  supportedOptions: LaunchOptionField[];
  value: LaunchOptions;
  onChange: (next: LaunchOptions) => void;
  placeholder?: string;
  /** What the backend found in these weights, when a specific model is in hand. */
  speculativeNote?: string | null;
  draftPlaceholder?: string;
}): JSX.Element {
  const patch = (part: Partial<LaunchOptions>): void =>
    props.onChange({ ...props.value, ...part });
  const supports = (field: LaunchOptionField): boolean =>
    props.supportedOptions.includes(field);

  // The argument field keeps its own raw text. Feeding the parsed array back through
  // `join(" ")` would swallow the space the operator just typed, so a second argument
  // could never be entered.
  const [rawArgs, setRawArgs] = createSignal(props.value.extraArgs.join(" "));
  const onArgsInput = (text: string): void => {
    setRawArgs(text);
    patch({ extraArgs: text.split(/\s+/).filter(Boolean) });
  };

  return (
    <Disclosure label="Advanced">
      <Stack gap={3}>
        <Text variant="micro" tone="dim">
          Leave these blank unless you have a reason. The engine sizes its own
          slots, GPU layers and batching, and blank means it keeps doing so.
        </Text>
        <Row gap={3} align="end" wrap>
          <Show when={supports("contextSize")}>
            <div class="min-w-0 flex-1">
              <Input
                label="Context size"
                type="number"
                inputMode="numeric"
                min="0"
                placeholder="auto"
                value={props.value.contextSize ?? ""}
                onInput={(e) =>
                  patch({ contextSize: toNumber(e.currentTarget.value) })
                }
                hint="Tokens one request may hold. Blank uses the model's own declared window, which can be far larger than your memory holds."
              />
            </div>
          </Show>
          <Show when={supports("cacheReuse")}>
            <div class="min-w-0 flex-1">
              <Input
                label="Cache reuse"
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
          </Show>
        </Row>
        <Show when={supports("kvCacheType")}>
          <Select
            label="KV cache type"
            options={KV_CACHE_OPTIONS}
            value={props.value.kvCacheType ?? ""}
            onChange={(v) =>
              patch({ kvCacheType: (v || null) as KvCacheType | null })
            }
            hint="Quantizing the cache buys back the memory a long context eats."
          />
        </Show>
        <Show when={supports("speculative")}>
          <Select
            label="Speculative decoding"
            options={SPECULATIVE_OPTIONS}
            value={props.value.speculative ?? ""}
            onChange={(v) =>
              patch({ speculative: (v || null) as SpeculativeMode | null })
            }
            hint={
              props.speculativeNote
                ? `This model: ${props.speculativeNote}.`
                : "Drafts several tokens per step and verifies them, when the model was trained with prediction heads. Auto turns it on only for weights that actually have them."
            }
          />
        </Show>
        <Show when={supports("draftModel")}>
          <Input
            label="Draft model"
            placeholder={
              props.draftPlaceholder ?? "org/model-MTP-4bit or /path/to/drafter"
            }
            value={props.value.draftModel ?? ""}
            onInput={(e) =>
              patch({ draftModel: e.currentTarget.value.trim() || null })
            }
            hint="A separate drafter, by repo id or path. It has to come from the same checkpoint as the model it drafts for."
          />
        </Show>
        <Input
          label="Extra arguments"
          placeholder={props.placeholder ?? "--cache-ram 16384"}
          value={rawArgs()}
          onInput={(e) => onArgsInput(e.currentTarget.value)}
          hint="Passed to the engine verbatim and unsupported — you own whatever you set here. A flag that one of the fields above would set is overridden by yours."
        />
      </Stack>
    </Disclosure>
  );
}
