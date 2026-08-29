import { Show, type JSX } from "solid-js";
import { Button, Row, Stack, StatusFlag, Text, Toggle } from "~/ui";
import type { EndpointDiscovery, ModelEndpoint } from "~/lib/stores/models";
import { EndpointDiscoveryFlag } from "./EndpointDiscoveryFlag";
import { EndpointHealthFlag } from "./EndpointHealthFlag";

/** One endpoint: what it is, what state it's in, and what can be done to it.
 *  Presentational — every action is the caller's. */
export function EndpointRow(props: {
  endpoint: ModelEndpoint;
  /** Resolved provider display name; falls back to the raw id upstream. */
  providerName: string;
  discovery?: EndpointDiscovery;
  testing: boolean;
  onToggleEnabled: () => void;
  onTest: () => void;
  onEdit: () => void;
  onDelete: () => void;
}): JSX.Element {
  const ep = () => props.endpoint;
  const summary = () =>
    [props.providerName, ep().model, ep().baseUrl].filter(Boolean).join(" · ");

  return (
    <Row align="center" justify="between" gap={3} class="py-2">
      <Stack gap={1} class={`min-w-0 ${ep().enabled ? "" : "opacity-40"}`}>
        <Row gap={2} align="center">
          <Text variant="label" tone="bright">
            {ep().name}
          </Text>
          <EndpointHealthFlag status={ep().lastStatus} />
          <Show when={!ep().enabled}>
            <StatusFlag status="warn">Disabled</StatusFlag>
          </Show>
          <Show when={ep().hasApiKey}>
            <StatusFlag status="nominal">Key</StatusFlag>
          </Show>
          <Show when={ep().vision}>
            <StatusFlag status="info">Vis</StatusFlag>
          </Show>
          <Show when={ep().thinking}>
            <StatusFlag status="info">Think</StatusFlag>
          </Show>
          <Show when={props.discovery}>
            {(d) => <EndpointDiscoveryFlag discovery={d()} />}
          </Show>
        </Row>
        <Text variant="micro" tone="dim" class="truncate">
          {summary()}
        </Text>
        {/* Backend-authored failure sentence — rendered verbatim. */}
        <Show when={ep().lastStatus === "error" && ep().lastErrorDetail}>
          <Text variant="micro" tone="alert">
            {ep().lastErrorDetail}
          </Text>
        </Show>
      </Stack>
      <span class="flex shrink-0 items-center gap-2">
        <Toggle checked={ep().enabled} onChange={props.onToggleEnabled} />
        <Button
          variant="ghost"
          size="sm"
          leading="refresh"
          disabled={props.testing}
          onClick={props.onTest}
        >
          {props.testing ? "Testing…" : "Test"}
        </Button>
        <Button variant="ghost" size="sm" leading="edit" onClick={props.onEdit}>
          Edit
        </Button>
        <Button
          variant="ghost"
          size="sm"
          leading="trash"
          onClick={props.onDelete}
        >
          Delete
        </Button>
      </span>
    </Row>
  );
}
