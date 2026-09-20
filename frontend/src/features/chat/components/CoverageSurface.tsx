/**
 * The shape of the investigation: how deep it got, where the holes are, and where the
 * sources disagree.
 *
 * The Agents panel answers "what did each sub-agent do" and answers it with a transcript
 * each, which is the right shape for the question it asks. This one asks the question a
 * fan-out actually raises — **is this enough to decide on?** — and no transcript answers
 * it, because the answer is a property of all of them together.
 *
 * **It leads with what has not arrived.** A map drawn from two of four reports looks
 * exactly like a finished one, so the arrival band sits at the top rather than in a
 * corner: a gap that is really "nobody has reported on this yet" must never read as
 * "nobody found anything". That band is also the panel's answer to the "sufficient to
 * decide?" checkpoint — not as a verdict the frontend computes, which would be the
 * frontend deciding, but as the three facts an operator settles it from: who is still
 * out, how deep each topic got, and what is still contested.
 *
 * **Filtered findings, not transcripts.** What a sub-agent established reaches this
 * panel as its own claims, filed under the topic it named and ranked by the confidence
 * it declared. Its prose report stays in the Agents panel, where reading it end to end
 * is the point.
 *
 * **No claim-level attribution.** A finding names the sources it rests on; nothing here
 * links a sentence of the answer to a sentence of a source. That decision is open, and
 * this panel has not pre-empted it.
 */

import { For, Show, type JSX } from "solid-js";
import { Collapse, EmptyState, StatusFlag, Text, type Status } from "~/ui";
import type { Depth } from "../data";
import {
  byConfidence,
  type CoverageReport,
  type TopicRow,
} from "../viewport/coverageItems";
import { ConflictCard } from "./ConflictCard";
import { FindingRow } from "./ResearchFindings";
import { ProcessRow, Sep, createAdoptedOpen } from "./ProcessRow";

/** Depth as a flag. **`none` is alert, not idle** — a topic a sub-agent looked at and
 *  got nowhere on is the single most actionable row a coverage map can carry, and the
 *  quiet tone is reserved for the rows that need nothing. */
const depthFlag: Record<Depth, Status> = {
  none: "alert",
  thin: "warn",
  adequate: "info",
  deep: "nominal",
};

export function CoverageSurface(props: {
  coverage: () => CoverageReport;
}): JSX.Element {
  const c = () => props.coverage();
  const empty = () =>
    c().topics.length === 0 &&
    c().conflicts.length === 0 &&
    c().untopiced.length === 0 &&
    c().unresolved.length === 0;

  return (
    <div class="flex h-full min-h-0 w-full flex-col gap-2 overflow-y-auto px-3 pb-2">
      <ArrivalBand coverage={c()} />
      <Show
        when={!empty()}
        fallback={
          <EmptyState
            icon="layers"
            message="Nothing mapped yet"
            hint="Topics, gaps and disagreements appear as researchers report back."
          />
        }
      >
        <Section label="Topics" count={c().topics.length}>
          <For each={c().topics}>{(row) => <TopicCard row={row} />}</For>
        </Section>
        <Section label="Disagreements" count={c().conflicts.length}>
          <For each={c().conflicts}>{(row) => <ConflictCard row={row} />}</For>
        </Section>
        <Section label="Findings without a topic" count={c().untopiced.length}>
          <div class="rounded-panel bg-surface px-2 shadow-1">
            <For each={byConfidence(c().untopiced)}>
              {(finding) => <FindingRow finding={finding} />}
            </For>
          </div>
        </Section>
        <Section label="Still unresolved" count={c().unresolved.length}>
          <div class="flex flex-col gap-1 rounded-panel bg-surface p-2 shadow-1">
            <For each={c().unresolved}>
              {(row) => (
                <div class="flex flex-col gap-0.5">
                  <Text
                    as="p"
                    variant="body"
                    tone="default"
                    class="break-words"
                  >
                    {row.question}
                  </Text>
                  <Text variant="micro" tone="dim">
                    {row.handle}
                  </Text>
                </div>
              )}
            </For>
          </div>
        </Section>
      </Show>
    </div>
  );
}

/** A heading and its rows, absent entirely when there are none. A permanently empty
 *  DISAGREEMENTS heading teaches the operator that headings here mean nothing. */
function Section(props: {
  label: string;
  count: number;
  children: JSX.Element;
}): JSX.Element {
  return (
    <Show when={props.count > 0}>
      <div class="flex flex-col gap-1.5">
        <div class="flex items-baseline gap-2 pt-1">
          <Text variant="plate" tone="dim">
            {props.label}
          </Text>
          <Text variant="micro" tone="dim" class="tabular-nums">
            {props.count}
          </Text>
        </div>
        {props.children}
      </div>
    </Show>
  );
}

/** How much of the investigation has actually reported — the honesty band.
 *
 *  Named rather than counted for the ones still out: "waiting on 2" and "waiting on
 *  `pricing-researcher` and `spec-reader`" are different sentences, and only the second
 *  lets the operator judge whether the gap in front of them is one those two will fill.
 *
 *  `proseOnly` is the quiet one and is why it is here at all: a sub-agent that finished
 *  without a structured block has done real work that this map cannot see. Its absence
 *  from the topics below is a property of the block, not of the research, and the map
 *  would otherwise present itself as complete while missing it. */
function ArrivalBand(props: { coverage: CoverageReport }): JSX.Element {
  const a = () => props.coverage.arrival;
  const waiting = () => a().outstanding.length > 0;
  return (
    <div class="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-line pb-2">
      <StatusFlag status={waiting() ? "info" : "nominal"} dot>
        {waiting() ? "In flight" : "All reported"}
      </StatusFlag>
      <Text variant="micro" tone="dim" class="tabular-nums">
        {a().reported} reported
      </Text>
      <Show when={waiting()}>
        <Sep />
        <Text variant="micro" tone="info" class="min-w-0 truncate">
          waiting on {a().outstanding.join(", ")}
        </Text>
      </Show>
      <Show when={a().proseOnly > 0}>
        <Sep />
        <Text variant="micro" tone="warn">
          {a().proseOnly} reported in prose only — read those in Agents
        </Text>
      </Show>
    </div>
  );
}

/** One topic: how deep, how many sources, what is missing, and — opened — what was
 *  actually established under it. */
function TopicCard(props: { row: TopicRow }): JSX.Element {
  const t = () => props.row;
  // **A gap opens the row.** The named holes are what the map is read for, and a hole
  // one click away is a hole nobody finds. The same rule the command log applies to a
  // failure, for the same reason.
  const { open, toggle } = createAdoptedOpen({}, t().gaps.length > 0);
  const findings = () => byConfidence(t().findings);

  return (
    <div class="overflow-hidden rounded-panel bg-surface shadow-1">
      <ProcessRow
        open={open()}
        onToggle={toggle}
        icon="layers"
        iconClass="text-dim"
        label="Topic"
        title={t().topic}
        class="hover:bg-raised"
        trailing={
          <>
            <Show when={t().gaps.length > 0}>
              <Text variant="micro" tone="warn" class="tabular-nums">
                {t().gaps.length} {t().gaps.length === 1 ? "gap" : "gaps"}
              </Text>
            </Show>
            {/* A topic that arrived only as a finding's label has made no depth claim,
                and `none` would be the report saying it got nowhere — which is a
                different and much stronger statement than saying nothing. */}
            <Show
              when={t().depthReported}
              fallback={
                <StatusFlag status="idle" dot>
                  depth not stated
                </StatusFlag>
              }
            >
              <StatusFlag status={depthFlag[t().depth]} dot>
                {t().depth}
              </StatusFlag>
            </Show>
          </>
        }
      >
        <Sep />
        <Text variant="micro" tone="default" class="min-w-0 truncate">
          {t().topic}
        </Text>
      </ProcessRow>
      <Collapse open={open()}>
        <div class="flex flex-col gap-1.5 bg-bg px-2 py-1.5">
          <div class="flex flex-wrap items-baseline gap-x-2">
            <Text variant="micro" tone="dim" class="tabular-nums">
              {t().sourceCount} {t().sourceCount === 1 ? "source" : "sources"}
            </Text>
            <Show when={t().reporters.length > 0}>
              <Sep />
              {/* Which sub-agents covered it — the per-topic arrival state, as far as
                  it goes. A topic nobody has reported on yet simply has no row here;
                  guessing which of the outstanding ones will cover it would be the
                  frontend deciding something. */}
              <Text variant="micro" tone="dim" class="min-w-0 truncate">
                {t().reporters.join(", ")}
              </Text>
            </Show>
          </div>
          <Show when={t().gaps.length > 0}>
            <div class="flex flex-col gap-0.5">
              <Text variant="plate" tone="warn">
                Gaps
              </Text>
              <For each={t().gaps}>
                {(gap) => (
                  <Text
                    as="p"
                    variant="body"
                    tone="default"
                    class="break-words"
                  >
                    {gap}
                  </Text>
                )}
              </For>
            </div>
          </Show>
          <Show when={findings().length > 0}>
            <div class="flex flex-col">
              <Text variant="plate" tone="dim">
                Established
              </Text>
              <For each={findings()}>
                {(finding) => <FindingRow finding={finding} />}
              </For>
            </div>
          </Show>
        </div>
      </Collapse>
    </div>
  );
}
