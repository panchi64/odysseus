import { For, Show, type JSX } from "solid-js";
import { Chip, Row, Stack, StatusFlag, Text } from "~/ui";
import type { EngineRecommendation } from "../model";
import { EngineInstallHint } from "./EngineInstallHint";

/** A single ranked engine: name, availability flag, reason, and workloads. The
 *  rank-1 engine leads. Read-only — an engine is a serving runtime, not a model,
 *  so there's nothing to serve/stop here (that lives on the managed-model rows). */
export function EngineRow(props: { rec: EngineRecommendation }): JSX.Element {
  return (
    <Stack gap={2} class="border-b border-line px-3 py-3 last:border-0">
      <Row align="center" justify="between" gap={3}>
        <Row align="center" gap={2} class="min-w-0">
          <Text variant="label" tone="bright">
            {props.rec.engine}
          </Text>
          <Show when={props.rec.rank === 1}>
            <StatusFlag status="info">RECOMMENDED</StatusFlag>
          </Show>
        </Row>
        <StatusFlag status={props.rec.available ? "nominal" : "idle"} dot>
          {props.rec.available ? "AVAILABLE" : "UNAVAILABLE"}
        </StatusFlag>
      </Row>
      <Text variant="micro" tone="dim">
        {props.rec.reason}
      </Text>
      <Show when={props.rec.available}>
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
  );
}
