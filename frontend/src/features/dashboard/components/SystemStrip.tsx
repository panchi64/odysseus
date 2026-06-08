import { For, type JSX } from "solid-js";
import { Marquee, Text, cx } from "~/ui";
import type { ServiceHealth, SystemStat } from "../mocks";

/** Maps a non-nominal service to its semantic dot color; nominal stays dim so a
 *  healthy strip is fully monochrome. */
const dotClass: Record<ServiceHealth["status"], string> = {
  nominal: "bg-dim",
  warn: "bg-warn",
  alert: "bg-alert",
};

export interface SystemStripProps {
  band: SystemStat[];
  services: ServiceHealth[];
}

/**
 * The most subtle component on the overview: a single dim telemetry strip of
 * model/system stats plus service dots. It stays a compact single line and only
 * scrolls (marquee) when the content can't fit — accent appears solely when a
 * service is degraded.
 */
export function SystemStrip(props: SystemStripProps): JSX.Element {
  return (
    <div class="flex min-w-0 items-center gap-2 border border-line bg-surface px-2 py-2">
      <Text variant="label" tone="dim" class="shrink-0">
        SYSTEM
      </Text>
      <Marquee class="min-w-0 flex-1" speed={32}>
        <div class="flex items-center gap-4">
          <For each={props.band}>
            {(stat) => (
              <span class="inline-flex items-center gap-1">
                <Text variant="label" tone="dim">
                  {stat.label}
                </Text>
                <Text variant="body" tone="dim">
                  {stat.value}
                </Text>
              </span>
            )}
          </For>
          <span
            class="inline-block h-3 w-px shrink-0 bg-line"
            aria-hidden="true"
          />
          <For each={props.services}>
            {(svc) => (
              <span class="inline-flex items-center gap-1">
                <span
                  class={cx(
                    "inline-block size-1.5 rounded-full",
                    dotClass[svc.status],
                  )}
                  aria-hidden="true"
                />
                <Text
                  variant="label"
                  tone={svc.status === "nominal" ? "dim" : svc.status}
                >
                  {svc.name}
                </Text>
              </span>
            )}
          </For>
        </div>
      </Marquee>
    </div>
  );
}
