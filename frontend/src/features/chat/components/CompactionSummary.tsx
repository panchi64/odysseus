import { For, Show, type JSX } from "solid-js";
import { Stack, Text } from "~/ui";
import type { SummarySection } from "~/lib/stream";

/** What the model is left holding after a fold, shown the way it is actually stored.
 *
 *  The summarizer is asked for eight fixed headings and the backend parses them, so the
 *  operator gets sections rather than a wall of text with `##` in it. Three rules decide
 *  how a section is set, and all three come off the wire rather than being guessed here:
 *
 *  - **The machine voice is for Anchors.** Its whole purpose is exact paths, ids and
 *    numbers carried across a fold character for character; setting those in the
 *    interface's sans voice invites the eye to read them as prose it can skim. Every other
 *    section is prose and takes the prose voice.
 *  - **Tool-derived text is attributed, never quoted silently.** A checkpoint is replayed
 *    to the model as a user-shaped message — the most authoritative voice in the history —
 *    and one section repeats what a web page or a file said. The backend fences it for the
 *    model; the operator gets the same fact as a bordered, labelled block. The fence's
 *    *markers* stay behind: the nonce is addressed to the model and is noise here.
 *  - **A section with no heading is a checkpoint that didn't parse.** Old checkpoints and
 *    summarizer drift degrade to one keyless section holding the whole text, which renders
 *    as what it is rather than as a structure it doesn't have.
 */
export function CompactionSummary(props: {
  sections: SummarySection[];
}): JSX.Element {
  return (
    <Stack gap={3}>
      <For each={props.sections}>
        {(section) => (
          <Stack gap={1}>
            {/* Keyless is the unparsed fallback — no heading to show. */}
            <Show when={section.key}>
              <Text variant="label" tone="dim">
                {section.key}
              </Text>
            </Show>
            <Show
              when={section.untrusted}
              fallback={<SectionBody section={section} />}
            >
              {/* Bordered and labelled: the same "this came from outside" the fence
                  makes to the model, in the form the operator reads. The border and
                  the words both carry it — colour never carries a distinction alone.
                  `Stack` rather than a bare div because `Text` is inline: the
                  attribution has to sit *above* the quote, not run into its first line. */}
              <Stack gap={1} class="border-l border-line pl-3">
                <Text variant="micro" tone="dim" class="italic">
                  Quoted from tool output — not this workspace's own words.
                </Text>
                <SectionBody section={section} />
              </Stack>
            </Show>
          </Stack>
        )}
      </For>
    </Stack>
  );
}

/** A section's text in the voice it asked for. `micro` is the mono machine register;
 *  `body` is the interface speaking. Both wrap on the stored line breaks, which are
 *  load-bearing in a bulleted Anchors list. */
function SectionBody(props: { section: SummarySection }): JSX.Element {
  return (
    <Text
      variant={props.section.voice === "machine" ? "micro" : "body"}
      tone="dim"
      class="whitespace-pre-wrap break-words"
    >
      {props.section.body}
    </Text>
  );
}
