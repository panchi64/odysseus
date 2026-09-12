import { type JSX } from "solid-js";
import { Icon, Stack, Text } from "~/ui";
import type { ChatMessage } from "../model";

/**
 * A sub-agent's report, where the thread received it.
 *
 * It arrives as a request message because that is the one shape a model has for anything
 * said to it from outside, and left alone it renders as a bubble on the operator's own
 * side of the thread — words attributed to them that they have not read and were never
 * asked about. So it is neither a bubble nor a divider: an inset note, set apart from both
 * sides, saying who reported and what they said.
 *
 * **No actions, deliberately.** Everything a turn usually offers — edit, fork, rewind,
 * retry — acts on something the operator said, and there is nothing here to send back to:
 * the sub-agent that wrote it has already ended. The report is also not the place to read
 * the work; the card in the Agents panel opens the whole transcript.
 */
export function SubagentReport(props: { message: ChatMessage }): JSX.Element {
  return (
    <Stack gap={1} class="border-line my-2 w-full border-l-2 py-1 pl-3">
      <div class="flex items-center gap-1.5">
        <Icon name="users" size={12} class="text-dim shrink-0" />
        <Text variant="micro" tone="dim">
          A sub-agent reported back
        </Text>
      </div>
      <Text variant="body" tone="dim" class="whitespace-pre-wrap">
        {props.message.content}
      </Text>
    </Stack>
  );
}
