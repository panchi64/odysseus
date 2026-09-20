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
import {
  Chip,
  Collapse,
  EmptyState,
  StatusFlag,
  Text,
  type Status,
} from "~/ui";
import { hostLabel, relativeTime } from "~/lib/format";
import {
  BUCKET_HINT,
  BUCKET_LABEL,
  type SourceBucket,
  type SourceInventory,
  type SourceItem,
} from "../viewport/sourceItems";
import { ProcessRow, Sep, createAdoptedOpen } from "./ProcessRow";

/** The shelf's own flag, in one word plus a tone. **Contradicted is the only one that
 *  raises its voice**, and it earns it: every other shelf reports how thoroughly a
 *  source was read, which is process, while this one reports that the sources disagree,
 *  which is a finding. The word carries it as well as the tone, so it still says which
 *  kind it is where the colour does not reach the reader. */
const bucketFlag: Record<SourceBucket, Status> = {
  contradicted: "warn",
  cited: "nominal",
  read: "info",
  listed: "idle",
};

export function SourcesSurface(props: {
  inventory: () => SourceInventory;
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
 *  `origins` is the independent-source count the requirement asks for, at the level it
 *  can honestly be given: a count of distinct publishers behind the thread's reading.
 *  Per-*claim* independence would need a claim→source link, which does not exist and is
 *  deliberately not being invented here. */
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

/** One source: what it is, where it came from, and — opened — the passage the run
 *  actually saw. */
function SourceRow(props: {
  item: SourceItem;
  bucket: SourceBucket;
}): JSX.Element {
  const s = () => props.item;
  const { open, toggle } = createAdoptedOpen({});
  const hasBody = () =>
    Boolean(s().snippet) || Boolean(s().url) || Boolean(s().ref);
  /** The row's name. A page's title, else its host; a passage's locator, else its
   *  source. Never the bare url — a row of full urls is a column nobody can scan. */
  const name = () =>
    s().title ||
    (s().url ? hostLabel(s().url!) : (s().ref ?? s().origin)) ||
    "Untitled";

  return (
    <div class="overflow-hidden rounded-panel bg-surface shadow-1">
      <ProcessRow
        open={open()}
        onToggle={toggle}
        icon={s().kind === "corpus" ? "library" : "link"}
        iconClass="text-dim"
        label={s().kind === "corpus" ? "Passage" : "Page"}
        title={name()}
        class="hover:bg-raised"
        trailing={
          <>
            {/* **How many times this thread came back to it.** A source seen once and a
                source seen four times are different things, and the count is the only
                evidence of that the fold leaves behind — everything else about the
                repeat sightings has been merged away. */}
            <Show when={s().sightings > 1}>
              <Text variant="micro" tone="dim" class="tabular-nums">
                ×{s().sightings}
              </Text>
            </Show>
            <StatusFlag status={bucketFlag[props.bucket]} dot>
              {BUCKET_LABEL[props.bucket]}
            </StatusFlag>
          </>
        }
      >
        <Sep />
        <Text variant="micro" tone="default" class="min-w-0 truncate">
          {name()}
        </Text>
      </ProcessRow>
      {/* `Collapse`, the same disclosure the command log uses — one animation vocabulary
          for "a row opening in a panel", not two. `hasBody` guards the content rather
          than the disclosure, so a row with nothing behind it still toggles without
          revealing an empty band. */}
      <Collapse open={open() && hasBody()}>
        <div class="flex flex-col gap-1.5 bg-bg px-2 py-1.5">
          <SourceDates item={s()} />
          <Show when={s().snippet}>
            {/* Reading scale, not `micro`. This is the one thing on the panel written
                by a human for humans — everything around it is the machine's record
                of what it did with it. */}
            <Text as="p" variant="body" tone="default" class="break-words">
              {s().snippet}
            </Text>
          </Show>
          <SourceAddress item={s()} />
        </div>
      </Collapse>
    </div>
  );
}

/** The two dates, kept apart because they answer different questions and only one of
 *  them can be trusted to be a date at all.
 *
 *  `published` is the source's own, passed through by the backend exactly as its
 *  provider reported it and never parsed — so it is printed verbatim, whatever shape it
 *  arrived in. `retrievedAt` is the backend's own ISO stamp for when *this run* read it,
 *  which is safe to make relative. Rendering both through one formatter would mean
 *  parsing a string the backend deliberately did not. */
function SourceDates(props: { item: SourceItem }): JSX.Element {
  const s = () => props.item;
  return (
    <Show when={s().published || s().retrievedAt}>
      <div class="flex flex-wrap items-baseline gap-x-2">
        <Show when={s().published}>
          <Text variant="micro" tone="dim">
            published {s().published}
          </Text>
        </Show>
        <Show when={s().published && s().retrievedAt}>
          <Sep />
        </Show>
        <Show when={s().retrievedAt}>
          <Text variant="micro" tone="dim">
            read {relativeTime(s().retrievedAt!)}
          </Text>
        </Show>
      </div>
    </Show>
  );
}

/** Where it lives. A page gets a chip that opens it; a corpus passage gets its locator
 *  as a static token, because there is no tab to open it in and a chip that opened
 *  `about:blank` would read as a broken link rather than as a source on the operator's
 *  own disk. The same rule the transcript's Sources row follows. */
function SourceAddress(props: { item: SourceItem }): JSX.Element {
  const s = () => props.item;
  return (
    <div class="flex flex-wrap items-center gap-2">
      <Show
        when={s().url}
        fallback={
          <Show when={s().ref}>
            <Chip leading="library">{s().ref}</Chip>
          </Show>
        }
      >
        <Chip
          leading="link"
          onClick={() => window.open(s().url!, "_blank", "noopener,noreferrer")}
        >
          {hostLabel(s().url!)}
        </Chip>
      </Show>
      <Show
        when={s().kind === "corpus" && s().origin && s().origin !== s().ref}
      >
        <Text variant="micro" tone="dim" class="min-w-0 truncate">
          {s().origin}
        </Text>
      </Show>
    </div>
  );
}
