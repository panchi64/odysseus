import { For, type JSX } from "solid-js";
import { Marquee, StatusDot, Text } from "~/ui";
import type { CapabilityHealth, SystemStat } from "../model";

export interface SystemStripProps {
  band: SystemStat[];
  capabilities: CapabilityHealth[];
}

/**
 * The most subtle component on the overview: a single dim telemetry strip of
 * model/system stats plus service dots. It stays a compact single line and only
 * scrolls (marquee) when the content can't fit.
 *
 * Every word here is machine output, so the whole strip is the **mono voice at
 * `micro`** (§2) — 10px, dim, no surface, no border. It was set in sans `label`
 * and `body` at 12–13px, which is interface-sized type: the same weight as
 * content the operator is meant to read, for content they are meant to skim
 * past. Accent appears only when a service is actually degraded.
 */
export function SystemStrip(props: SystemStripProps): JSX.Element {
  return (
    // No surface and no border: this is ambient telemetry, and giving it a card
    // made the quietest thing on the page into another object competing with the
    // composer. It sits directly on the ground now.
    <div class="flex min-w-0 items-center gap-2 py-2">
      <Text variant="meta" tone="dim" class="shrink-0">
        System
      </Text>
      <Marquee class="min-w-0 flex-1" speed={32}>
        <div class="flex items-center gap-4">
          <For each={props.band}>
            {(stat) => (
              <span class="inline-flex items-center gap-1">
                <Text variant="micro" tone="dim">
                  {stat.label}
                </Text>
                <Text variant="micro" tone="dim">
                  {stat.value}
                </Text>
              </span>
            )}
          </For>
          <span
            class="inline-block h-3 w-px shrink-0 bg-line"
            aria-hidden="true"
          />
          <For each={props.capabilities}>
            {(cap) => (
              <span class="inline-flex items-center gap-1">
                <StatusDot status={cap.status} />
                {/* The dot carries the state; the name stays dim unless the
                    capability is genuinely degraded (§10.5). A row of coloured
                    service names is a row of alarms for a system that is fine. */}
                <Text
                  variant="micro"
                  tone={
                    cap.status === "warn" || cap.status === "alert"
                      ? cap.status
                      : "dim"
                  }
                >
                  {cap.label}
                </Text>
              </span>
            )}
          </For>
        </div>
      </Marquee>
    </div>
  );
}
