import { For, Show, type JSX } from "solid-js";
import { Chip, cx, Row, Stack, StatusFlag, Text } from "~/ui";
import type { EngineKind } from "~/lib/api/models-types";
import type { EngineRecommendation } from "../model";
import { EngineInstallHint } from "./EngineInstallHint";

/** One selectable engine option in the picker: name, RECOMMENDED + availability flags,
 *  the plain-language reason, install state, and the workloads it covers. The rank-1
 *  engine carries RECOMMENDED. Available engines are selectable (radio semantics); an
 *  engine this host can't run is disabled and dimmed but still shown with its reason, so
 *  the operator sees *why* it's unavailable rather than guessing. Selection lifts the row
 *  to `surface-raised` behind a 2px emphasis bar — brightness + border, never a color
 *  accent (design §6.6 / states table). The bar slot is always 2px so selecting never
 *  shifts the layout. */
export function EngineRow(props: {
  rec: EngineRecommendation;
  selected: boolean;
  onSelect: (engine: EngineKind) => void;
}): JSX.Element {
  const available = () => props.rec.available;
  return (
    <button
      type="button"
      role="radio"
      aria-checked={props.selected}
      disabled={!available()}
      onClick={() => props.onSelect(props.rec.engine)}
      class={cx(
        "block w-full border-b border-line text-left transition-colors last:border-0",
        available()
          ? props.selected
            ? "bg-raised"
            : "hover:bg-raised"
          : "cursor-not-allowed",
      )}
    >
      <Row align="stretch" gap={0}>
        <div
          class={cx(
            "w-0.5 shrink-0",
            props.selected ? "bg-bright" : "bg-transparent",
          )}
        />
        <Stack gap={2} class="min-w-0 flex-1 px-3 py-3">
          <Row align="center" justify="between" gap={3}>
            <Row align="center" gap={2} class="min-w-0">
              <Text variant="label" tone={available() ? "bright" : "dim"}>
                {props.rec.engine}
              </Text>
              <Show when={props.rec.rank === 1}>
                <StatusFlag status="info">RECOMMENDED</StatusFlag>
              </Show>
            </Row>
            <StatusFlag status={available() ? "nominal" : "idle"} dot>
              {available() ? "AVAILABLE" : "UNAVAILABLE"}
            </StatusFlag>
          </Row>
          <Text variant="micro" tone="dim">
            {props.rec.reason}
          </Text>
          <Show when={available()}>
            <EngineInstallHint installed={props.rec.installed} />
          </Show>
          <Show when={props.rec.workloads.length}>
            <Row gap={2} align="center" class="flex-wrap">
              <For each={props.rec.workloads}>
                {(w) => <Chip>{w.toUpperCase()}</Chip>}
              </For>
            </Row>
          </Show>
        </Stack>
      </Row>
    </button>
  );
}
