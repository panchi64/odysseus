import { Show, type JSX } from "solid-js";
import {
  Field,
  Input,
  Row,
  Select,
  type SelectOption,
  StatusFlag,
  Stack,
  Text,
  Toggle,
} from "~/ui";

/** The endpoint form's field state — the single shape both the Settings modal
 *  (advanced) and the guided cookbook tab (simple) drive. Held by the parent so
 *  this stays a pure presentation control: it renders fields and relays changes,
 *  it owns no state and makes no decision. */
export interface EndpointFormValues {
  name: string;
  baseUrl: string;
  /** The provider adapter id (from `GET /models/providers`). */
  provider: string;
  model: string;
  apiKey: string;
  contextWindow: string;
  nativeTools: boolean;
  vision: boolean;
  thinking: boolean;
}

export interface EndpointFormProps {
  values: EndpointFormValues;
  onChange: <K extends keyof EndpointFormValues>(
    key: K,
    value: EndpointFormValues[K],
  ) => void;
  /** `advanced` (Settings) shows every field; `simple` (guided setup) shows only
   *  the API-key field with a preset-prefilled, read-only name/base URL summary
   *  plus the needs-a-key badge. */
  variant?: "advanced" | "simple";
  /** Edit mode relabels the key field (blank = leave the stored key unchanged). */
  editing?: boolean;
  /** Simple mode only: whether the chosen preset needs a key — drives the badge
   *  and the key field's optionality copy. */
  requiresKey?: boolean;
  /** Simple mode only: whether the base URL is operator-typed (the chosen
   *  provider carries no default) rather than shown as a read-only summary. */
  baseUrlEditable?: boolean;
  /** Advanced mode only: the provider choices (from `GET /models/providers`).
   *  Omitted ⇒ no provider select is rendered. */
  providerOptions?: SelectOption[];
  /** The chosen provider's key hint (e.g. "sk-ant-…"), shown on the key field. */
  keyHint?: string;
}

/** The shared create/edit endpoint form body. ONE form, two variants — so the
 *  Settings modal and the guided cookbook tab never drift. */
export function EndpointForm(props: EndpointFormProps): JSX.Element {
  const v = () => props.values;
  const simple = () => props.variant === "simple";

  return (
    <Stack gap={3}>
      <Show
        when={simple()}
        fallback={
          <Input
            label="Name"
            value={v().name}
            onInput={(e) => props.onChange("name", e.currentTarget.value)}
            placeholder="e.g. local-qwen"
          />
        }
      >
        {/* Simple mode: name comes from the provider preset — show it as a
            read-only summary so the operator sees what they're connecting to.
            The base URL is the preset's when it carries one, typed otherwise. */}
        <Stack gap={1}>
          <Row gap={2} align="center">
            <Text variant="label" tone="bright">
              {v().name}
            </Text>
            <StatusFlag status={props.requiresKey ? "warn" : "nominal"}>
              {props.requiresKey ? "Needs a key" : "No key needed"}
            </StatusFlag>
          </Row>
          <Show when={!props.baseUrlEditable}>
            <Text variant="micro" tone="dim" class="truncate">
              {v().baseUrl}
            </Text>
          </Show>
        </Stack>
      </Show>

      <Show when={!simple() && props.providerOptions}>
        {(options) => (
          <Select
            label="Provider"
            value={v().provider}
            options={options()}
            onChange={(id) => props.onChange("provider", id)}
            hint="How Odysseus talks to this endpoint. Presets prefill the base URL."
          />
        )}
      </Show>

      <Show when={!simple() || props.baseUrlEditable}>
        <Input
          label="Base URL"
          value={v().baseUrl}
          onInput={(e) => props.onChange("baseUrl", e.currentTarget.value)}
          placeholder="http://localhost:11434/v1"
        />
      </Show>

      <Show when={!simple()}>
        <Input
          label="DEFAULT MODEL (optional)"
          value={v().model}
          onInput={(e) => props.onChange("model", e.currentTarget.value)}
          placeholder="qwen2.5-coder:32b"
          hint="Models are discovered from the provider and picked in the top bar. Set a default only as a fallback for providers without a models API."
        />
      </Show>

      {/* The key field is the heart of the simple flow; in advanced mode it sits
          alongside the rest. Hidden when a preset needs none. */}
      <Show when={!simple() || props.requiresKey}>
        <Input
          label={
            props.editing
              ? "API KEY (blank = unchanged)"
              : simple()
                ? "API key"
                : "API KEY (optional)"
          }
          type="password"
          value={v().apiKey}
          onInput={(e) => props.onChange("apiKey", e.currentTarget.value)}
          placeholder={props.keyHint ?? "••••••••"}
        />
      </Show>

      <Show when={!simple()}>
        <Input
          label="CONTEXT WINDOW (optional)"
          value={v().contextWindow}
          onInput={(e) =>
            props.onChange("contextWindow", e.currentTarget.value)
          }
          placeholder="32768"
        />
        <Row gap={4} align="center" justify="between">
          <Field label="Native tools" orientation="row" value="" />
          <Toggle
            checked={v().nativeTools}
            onChange={(c) => props.onChange("nativeTools", c)}
          />
        </Row>
        <Row gap={4} align="center" justify="between">
          <Field label="Vision" orientation="row" value="" />
          <Toggle
            checked={v().vision}
            onChange={(c) => props.onChange("vision", c)}
          />
        </Row>
        <Row gap={4} align="center" justify="between">
          <Field label="Thinking" orientation="row" value="" />
          <Toggle
            checked={v().thinking}
            onChange={(c) => props.onChange("thinking", c)}
          />
        </Row>
      </Show>
    </Stack>
  );
}
