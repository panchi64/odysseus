import { Show, type JSX } from "solid-js";
import { Button, type IconName, ListRow, Row, StatusFlag, Text } from "~/ui";
import { bytes } from "~/lib/format";
import type { CatalogEntry } from "../model";

/** One curated catalog model — label + params/quant/size meta, a TOOLS flag when
 *  it supports native tool-calling, and a single action button. Shared by the
 *  LOCAL MODELS catalog (DOWNLOAD) and the EMBEDDING serve-locally catalog
 *  (DOWNLOAD & SERVE); the cosmetic differences (leading icon, action icon/label,
 *  and the action handler) are props, not a fork. The action is disabled while a
 *  matching managed model is already in flight. */
export function CatalogRow(props: {
  entry: CatalogEntry;
  /** Leading row icon. */
  leading: IconName;
  /** Action button icon. */
  actionIcon: IconName;
  /** Action button label at rest. */
  actionLabel: string;
  /** Action button label while in flight (also disables the button). */
  busyLabel: string;
  /** Whether a matching managed model is already in flight. */
  inFlight: boolean;
  onAction: () => void;
}): JSX.Element {
  return (
    <ListRow
      label={props.entry.label}
      leading={props.leading}
      right={
        <Row gap={2} align="center">
          <Show when={props.entry.params}>
            <Text variant="micro" tone="dim">
              {props.entry.params}
            </Text>
          </Show>
          <Show when={props.entry.quant}>
            <Text variant="micro" tone="dim">
              {props.entry.quant}
            </Text>
          </Show>
          <Show when={props.entry.approxBytes != null}>
            <Text variant="micro" tone="dim">
              {bytes(props.entry.approxBytes!)}
            </Text>
          </Show>
          <Show when={props.entry.nativeTools}>
            <StatusFlag status="nominal">TOOLS</StatusFlag>
          </Show>
          <Button
            size="sm"
            leading={props.actionIcon}
            disabled={props.inFlight}
            onClick={props.onAction}
          >
            {props.inFlight ? props.busyLabel : props.actionLabel}
          </Button>
        </Row>
      }
    />
  );
}
