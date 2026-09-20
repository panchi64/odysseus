/**
 * A question the sources answered differently, rendered as the comparison it is.
 *
 * **This is the structured comparison of options, and the reason it has its own shape.**
 * Every other way of showing a disagreement flattens it: prose picks a side in the act of
 * summarizing, and a bullet list of claims loses which sources stand behind which. What
 * makes a conflict readable is that the positions sit in parallel — same anatomy, same
 * scale, side by side — so the operator compares claims against claims and source counts
 * against source counts rather than reading two paragraphs and trying to hold the first
 * one in their head.
 *
 * Three rules, each protecting the comparison from becoming a conclusion:
 *
 * - **Every position renders, at the same weight.** The panel takes no side and gives
 *   none of them a tone; the sub-agent's assessment is a separate, attributed row
 *   beneath, not a highlight on the position it favours.
 * - **The assessment names its author.** It is one sub-agent's judgement, and an
 *   unattributed judgement reads as the system's verdict.
 * - **A conflict with one position is still a conflict** — a sub-agent that named a
 *   disagreement and then listed only one side has told the operator something, and
 *   hiding the row would hide that too.
 */

import { For, Show, type JSX } from "solid-js";
import { ConsoleGroup, Text } from "~/ui";
import type { ConflictRow } from "../viewport/coverageItems";
import { SourceTokens } from "./ResearchFindings";

export function ConflictCard(props: { row: ConflictRow }): JSX.Element {
  const c = () => props.row.conflict;
  return (
    <ConsoleGroup
      label="Disagreement"
      right={
        <Text variant="micro" tone="dim" class="min-w-0 truncate">
          {props.row.handle}
        </Text>
      }
    >
      <div class="flex flex-col gap-2 px-1 py-0.5">
        {/* The question, at reading scale — it is the one sentence here written to be
            read as a sentence, and everything below it is an answer to it. */}
        <Text as="p" variant="body" tone="bright" class="break-words">
          {c().question}
        </Text>
        <Show
          when={c().positions.length}
          fallback={
            <Text variant="micro" tone="dim">
              No positions were recorded for this disagreement.
            </Text>
          }
        >
          {/* **Columns where there is room, stacked where there is not.** The whole
              value of the layout is reading two claims against each other, which needs
              them beside each other — and a 340px pane cannot give two columns without
              breaking every line in both. `sm` is where the pane stops being a strip of
              text. Three or more positions wrap into the same grid rather than
              compressing further. */}
          <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <For each={c().positions}>
              {(position) => (
                <div class="flex min-w-0 flex-col gap-1 rounded-panel bg-raised p-2">
                  <Text
                    as="p"
                    variant="body"
                    tone="default"
                    class="break-words"
                  >
                    {position.claim}
                  </Text>
                  <SourceTokens sources={position.sources} />
                </div>
              )}
            </For>
          </div>
        </Show>
        <Show when={c().assessment}>
          <div class="flex flex-col gap-0.5 border-t border-line pt-1.5">
            <Text variant="plate" tone="dim">
              {props.row.handle} judges
            </Text>
            <Text as="p" variant="body" tone="default" class="break-words">
              {c().assessment}
            </Text>
          </div>
        </Show>
      </div>
    </ConsoleGroup>
  );
}
