/**
 * Everything a research thread read, as one inventory.
 *
 * The transcript already shows the handful of links an answer leaned on, and that is the
 * right place to *follow* one. It is the wrong place to answer the question this panel
 * exists for: **what is all of this resting on, and what did it look at and put down?**
 * In the transcript a source is three chips under one answer, separated from the next
 * turn's three by half a screen of prose — so "did anything else say this" is answered by
 * scrolling and remembering. Here they are one column, filed by how far the run actually
 * got with each.
 *
 * Three things the panel is careful about, each because the honest version is less
 * flattering than the easy one:
 *
 * - **It does not number.** The turn's Sources row numbers within the turn; numbering
 *   again across the thread would make `[3]` there and `[17]` here the same page.
 * - **`Listed, never opened` says exactly what is known.** The requirement asks for
 *   discarded sources *with reasons*, and the only reason the system holds is the
 *   structural one. A richer sentence would be invented.
 * - **`origins` is printed beside the source count, never instead of it.** Five pages off
 *   one site are five sources and one origin, and an inventory that reported only the
 *   first figure would read as five times the corroboration it has.
 *
 * Read-only. A source is opened in a browser tab or it is not; there is nothing to decide
 * here, and the corpus passages have nowhere to be opened to.
 */

import { For, Show, type JSX } from "solid-js";
import { EmptyState, Text } from "~/ui";
import { relativeTime } from "~/lib/format";
import {
  BUCKET_HINT,
  BUCKET_LABEL,
  type SourceInventory,
} from "../viewport/sourceItems";
import { Sep } from "./ProcessRow";
import { SourceRow } from "./SourceRow";
import { ClaimsSection } from "./ClaimsSection";
import type { ClaimInventory } from "../viewport/claimItems";

export function SourcesSurface(props: {
  inventory: () => SourceInventory;
  /** What a second reader found in this thread's answers — empty for most threads. */
  claims: () => ClaimInventory;
  /** Whether asking for a reading is worth offering here. */
  canExtract: () => boolean;
  onExtract: () => void;
  extracting: () => boolean;
}): JSX.Element {
  const inv = () => props.inventory();
  return (
    <div class="flex h-full min-h-0 w-full flex-col gap-2 overflow-y-auto px-3 pb-2">
      <Show
        when={inv().items.length}
        fallback={
          <EmptyState
            icon="search"
            message="No sources yet"
            hint="What this thread reads — the web and your knowledge base — lands here."
          />
        }
      >
        <InventoryHead inventory={inv()} />
        {/* **Above the inventory, deliberately.** The inventory answers "what did this
            read"; the claims answer "is what it wrote actually in there", which is the
            harder question and the one an operator opens this panel carrying. */}
        <ClaimsSection
          claims={props.claims()}
          canExtract={props.canExtract()}
          onExtract={props.onExtract}
          extracting={props.extracting()}
        />
        <For each={inv().groups}>
          {(group) => (
            <div class="flex flex-col gap-1">
              <div class="flex items-baseline gap-2 pt-1">
                <Text variant="plate" tone="dim">
                  {BUCKET_LABEL[group.bucket]}
                </Text>
                <Text variant="micro" tone="dim" class="tabular-nums">
                  {group.items.length}
                </Text>
              </div>
              <Text variant="micro" tone="dim">
                {BUCKET_HINT[group.bucket]}
              </Text>
              <For each={group.items}>
                {(item) => <SourceRow item={item} bucket={group.bucket} />}
              </For>
            </div>
          )}
        </For>
      </Show>
    </div>
  );
}

/** The two figures the whole inventory is read against, and when it was last added to.
 *
 *  `origins` is the independent-source count at the **thread** level: distinct publishers
 *  behind everything this thread read. Per-*claim* independence is a different figure and
 *  it now exists — the claims section above carries it, counted the same way over the
 *  sources one assertion rests on. Both are printed because they answer different
 *  questions, and neither stands in for the other. */
function InventoryHead(props: { inventory: SourceInventory }): JSX.Element {
  const inv = () => props.inventory;
  return (
    <div class="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-b border-line pb-2">
      <Text variant="micro" tone="bright" class="tabular-nums">
        {inv().items.length} {inv().items.length === 1 ? "source" : "sources"}
      </Text>
      <Sep />
      <Text variant="micro" tone="dim" class="tabular-nums">
        {inv().originCount}{" "}
        {inv().originCount === 1 ? "origin" : "independent origins"}
      </Text>
      <Show when={inv().newestRetrieval}>
        <Sep />
        <Text variant="micro" tone="dim">
          last read {relativeTime(inv().newestRetrieval!)}
        </Text>
      </Show>
    </div>
  );
}
