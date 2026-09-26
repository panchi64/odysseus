import { For, Show, type JSX } from "solid-js";
import { Button, Chip, StatusFlag, Text } from "~/ui";
import { hostLabel, relativeTime } from "~/lib/format";
import type {
  ClaimInventory,
  ClaimRow,
  ClaimSource,
} from "../viewport/claimItems";
import { Sep, createAdoptedOpen } from "./ProcessRow";
import { SurfaceCard, SurfaceSection } from "./surfaceChrome";

/**
 * What a second reader found when it read the answer against its own sources.
 *
 * **The ungrounded row is the product.** Everything else on this panel reports what the
 * thread did; this reports whether what it wrote is actually in what it read. A claim
 * whose own cited source does not appear to support it is the exact defect the feature
 * was built to find, so it leads, it keeps its source (the operator wants to go and
 * look), and it is flagged in a word as well as a tone.
 *
 * **Absent is ordinary and renders as nothing.** Most threads have no reading — every
 * non-research thread, and every research answer that cited nothing. The section is not
 * drawn at all rather than shown as an empty heading, with one exception: a thread that
 * has sources and no reading is offered one, because that is the retroactive path and
 * the operator cannot know it exists otherwise.
 */
export function ClaimsSection(props: {
  claims: ClaimInventory;
  /** Whether this thread could have a reading — offered only where it is worth asking. */
  canExtract: boolean;
  onExtract: () => void;
  extracting: boolean;
}): JSX.Element {
  const c = () => props.claims;
  return (
    <Show
      when={c().items.length > 0}
      fallback={
        <Show when={props.canExtract}>
          <SurfaceSection
            label="Claims"
            hint="Nothing has read this answer against its sources yet."
            ruled
          >
            <div>
              <Button
                variant="ghost"
                size="sm"
                leading="search"
                disabled={props.extracting}
                onClick={props.onExtract}
              >
                {props.extracting ? "Reading…" : "Check the claims"}
              </Button>
            </div>
          </SurfaceSection>
        </Show>
      }
    >
      <SurfaceSection
        label="Claims"
        count={c().items.length}
        countTone="bright"
        ruled
        columns
        extra={
          <>
            {/* Printed whenever there is a reading at all, including as a zero — "none
                ungrounded" is a result the operator came for, and hiding it would make
                the absence of the line indistinguishable from the absence of the check. */}
            <Sep />
            <Text
              variant="micro"
              tone={c().ungroundedCount > 0 ? "warn" : "dim"}
              class="tabular-nums"
            >
              {c().ungroundedCount} unsupported
            </Text>
            <Show when={c().newestExtraction}>
              <Sep />
              <Text variant="micro" tone="dim">
                read {relativeTime(c().newestExtraction!)}
              </Text>
            </Show>
          </>
        }
      >
        <For each={c().items}>{(row) => <ClaimCard row={row} />}</For>
      </SurfaceSection>
    </Show>
  );
}

/** One assertion, and everything found to stand behind it. */
function ClaimCard(props: { row: ClaimRow }): JSX.Element {
  const r = () => props.row;
  const { open, toggle } = createAdoptedOpen({});
  return (
    <SurfaceCard
      open={open()}
      onToggle={toggle}
      icon={r().grounded ? "check" : "warning"}
      iconClass={r().grounded ? "text-dim" : "text-warn"}
      label={r().grounded ? "Claim" : "Unsupported"}
      title={r().claim}
      detail={r().claim}
      trailing={
        <>
          {/* The per-claim independent-source count — corroboration for *this*
              assertion, which the thread-wide origin figure cannot give. Counted in
              origins, so four pages off one site do not read as four. */}
          <Show when={r().origins > 1}>
            <Text variant="micro" tone="dim" class="tabular-nums">
              {r().origins} origins
            </Text>
          </Show>
          <Show when={!r().grounded}>
            <StatusFlag status="warn" dot>
              No passage
            </StatusFlag>
          </Show>
        </>
      }
    >
      {/* Reading scale: the claim is prose, and it is the thing being judged. */}
      <Text as="p" variant="body" tone="default" class="break-words">
        {r().claim}
      </Text>
      <Show
        when={r().sources.length > 0}
        fallback={
          <Text variant="micro" tone="dim">
            The reader could not name a source for this.
          </Text>
        }
      >
        <For each={r().sources}>{(s) => <ClaimSourceRow source={s} />}</For>
      </Show>
      <Show when={!r().grounded}>
        {/* Said plainly, and said as what it is: a second reader's failure to find
            the assertion, not a verdict that the answer is wrong. */}
        <Text variant="micro" tone="warn">
          A second reader did not find this in the source above.
        </Text>
      </Show>
      <Text variant="micro" tone="dim">
        confidence {r().confidence}
      </Text>
    </SurfaceCard>
  );
}

/** One source under a claim: where it is, and the sentence that was found in it. */
function ClaimSourceRow(props: { source: ClaimSource }): JSX.Element {
  const s = () => props.source;
  const name = () =>
    s().title || (s().url ? hostLabel(s().url!) : (s().key ?? "Source"));
  return (
    <div class="flex flex-col gap-1 border-l border-line pl-2">
      <Show when={s().url} fallback={<Chip leading="library">{name()}</Chip>}>
        <Chip
          leading="link"
          onClick={() => window.open(s().url!, "_blank", "noopener,noreferrer")}
        >
          {name()}
        </Chip>
      </Show>
      <Show when={s().passage}>
        <Text as="p" variant="body" tone="dim" class="break-words">
          “{s().passage}”
        </Text>
      </Show>
    </div>
  );
}
