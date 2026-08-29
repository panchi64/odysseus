import { Show, type JSX } from "solid-js";
import { Chip, Combobox, Panel, Row, Stack, Text } from "~/ui";
import { num } from "~/lib/format";
import type { ModelEndpoint } from "~/lib/stores/models";
import { EndpointHealthFlag } from "./EndpointHealthFlag";

/** One job, one model. The card names the job in plain language, offers ONE
 *  combined picker (a model, with its endpoint implied by the choice), and shows
 *  the live facts about whatever is currently chosen so the pick is informed.
 *
 *  Purely presentational: the caller supplies the options, the current value, and
 *  what a pick means. Every fact rendered here is a field the backend already
 *  reports on the endpoint — nothing is derived or judged locally. */
export interface ModelRoleCardProps {
  /** Uppercase panel label — the job, not the role name (e.g. "Chat model"). */
  label: string;
  /** One sentence saying what this model actually does for the operator. */
  description: string;
  /** Grouped picker options, one group per endpoint (plus any caller-local
   *  option, e.g. "Same as chat model"). */
  groups: { label: string; options: { value: string; label: string }[] }[];
  value: string;
  onChange: (value: string) => void;
  /** Fired when the picker opens — the caller re-asks its endpoints what they serve,
   *  so a model that appeared since the page loaded is in the list being looked at. */
  onOpen?: () => void;
  /** Trigger text when nothing is chosen. */
  placeholder: string;
  /** The endpoint backing the current choice — the source of the facts row. */
  endpoint?: ModelEndpoint;
  /** Extra controls belonging to this job (e.g. the re-embed readout). */
  children?: JSX.Element;
}

export function ModelRoleCard(props: ModelRoleCardProps): JSX.Element {
  return (
    <Panel label={props.label}>
      <Stack gap={3}>
        <Text variant="micro" tone="dim">
          {props.description}
        </Text>

        <Combobox
          groups={props.groups}
          value={props.value}
          onChange={props.onChange}
          onOpen={props.onOpen}
          leading="cpu"
          placeholder={props.placeholder}
          searchPlaceholder="Search models…"
          emptyHint="No models — add an endpoint under advanced"
          aria-label={props.label}
        />

        {/* The facts the backend reports about the chosen model's endpoint. */}
        <Show when={props.endpoint}>
          {(ep) => (
            <Row gap={2} align="center" class="flex-wrap">
              <Text variant="micro" tone="dim">
                {ep().name}
              </Text>
              <EndpointHealthFlag status={ep().lastStatus} />
              <Show when={ep().contextWindow}>
                {(cw) => <Chip>CTX {num(cw(), 0)}</Chip>}
              </Show>
              <Show when={ep().nativeTools}>
                <Chip>Tools</Chip>
              </Show>
              <Show when={ep().vision}>
                <Chip>Vision</Chip>
              </Show>
            </Row>
          )}
        </Show>

        {props.children}
      </Stack>
    </Panel>
  );
}
