/**
 * The two pieces every structured report is built out of: a claim, and who said it.
 *
 * Shared by the coverage map and the conflict comparison rather than written twice,
 * because they are the same two things in both places — a finding is a claim with its
 * sources, and a side of a disagreement is a claim with its sources. Writing them twice
 * is how the two would end up disagreeing about what a source looks like.
 */

import { For, Show, type JSX } from "solid-js";
import { Chip, Text, type TextTone } from "~/ui";
import { hostLabel } from "~/lib/format";
import type { Confidence, Finding, ReportSource } from "../data";

/** **Confidence is a word before it is a colour.** It is the report's own judgement of
 *  its own claim, which is exactly the kind of thing an operator scrolls past when it is
 *  carried by a tint alone — and exactly the kind of thing they should not. */
const confidenceTone: Record<Confidence, TextTone> = {
  high: "nominal",
  medium: "dim",
  low: "warn",
};

/** One thing a sub-agent established: the statement, how sure it is, and what it rests
 *  on.
 *
 *  **The sources are the point, not decoration.** A finding without them is an assertion,
 *  and the count is what the requirement's "independent-source count" means at the level
 *  the data supports: how many separate things the sub-agent read before writing this
 *  sentence. */
export function FindingRow(props: { finding: Finding }): JSX.Element {
  const f = () => props.finding;
  return (
    <div class="flex flex-col gap-1 py-1.5">
      <div class="flex items-baseline gap-2">
        <Text
          variant="micro"
          tone={confidenceTone[f().confidence]}
          class="shrink-0"
        >
          {f().confidence}
        </Text>
        <Text as="p" variant="body" tone="default" class="min-w-0 break-words">
          {f().statement}
        </Text>
      </div>
      <SourceTokens sources={f().sources} />
    </div>
  );
}

/** The sources behind a claim, as tokens.
 *
 *  A page opens; a corpus passage does not — it has a locator rather than an address,
 *  and a chip that opened `about:blank` would read as a broken link rather than as a
 *  source on the operator's own disk. The same rule the transcript's Sources row and the
 *  Sources panel both keep.
 *
 *  **Says so when there are none.** A finding a sub-agent wrote with no sources under it
 *  is worth reading differently from one with four, and a row that simply rendered
 *  nothing would make the two look identical. */
export function SourceTokens(props: { sources: ReportSource[] }): JSX.Element {
  return (
    <Show
      when={props.sources.length}
      fallback={
        <Text variant="micro" tone="warn">
          no sources named
        </Text>
      }
    >
      <div class="flex flex-wrap items-center gap-1.5">
        <Text variant="micro" tone="dim" class="tabular-nums">
          {props.sources.length}{" "}
          {props.sources.length === 1 ? "source" : "sources"}
        </Text>
        <For each={props.sources}>{(s) => <SourceToken source={s} />}</For>
      </div>
    </Show>
  );
}

function SourceToken(props: { source: ReportSource }): JSX.Element {
  const s = () => props.source;
  const label = () =>
    s().title || (s().url ? hostLabel(s().url!) : (s().ref ?? "source"));
  return (
    <Show when={s().url} fallback={<Chip leading="library">{label()}</Chip>}>
      <Chip
        leading="link"
        onClick={() => window.open(s().url!, "_blank", "noopener,noreferrer")}
      >
        {label()}
      </Chip>
    </Show>
  );
}
