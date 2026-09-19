import { For, type JSX } from "solid-js";
import { Marquee, Text } from "~/ui";
import type { SystemStat } from "../model";

export interface SystemStripProps {
  band: SystemStat[];
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
 * past.
 *
 * **Capability health left this strip for the annunciator grid** (`~/ui`
 * `AnnunciatorGrid`, §10.15). A row of service dots inline with the facts band made
 * every capability equally loud and equally easy to skim past, which is the wrong
 * reading for the one thing on this strip that can be *wrong*. What stays here is
 * genuinely ambient — counts and versions, nothing that ever needs the operator.
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
        </div>
      </Marquee>
    </div>
  );
}
