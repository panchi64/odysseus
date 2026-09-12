import { For, Match, Show, Switch, type JSX } from "solid-js";
import { LoadingText, Text } from "~/ui";
import { useChatSession, type Subagent } from "../data";
import { isLive } from "../data";
import { TurnBlocks } from "./TurnBlocks";

/**
 * What a sub-agent actually did, under its card.
 *
 * **It is a conversation, so it is read as one.** `useChatSession` is the main room's
 * own loader and `TurnBlocks` its own renderer — the think → tool → text sequence, the
 * work log, the folding, all of it — so a sub-agent's transcript reads exactly like the
 * agent's own work, which is what it is. Writing a second, simpler renderer here would
 * have meant a transcript that quietly showed less than the real one.
 *
 * **`TurnBlocks`, not `MessageItem`.** That wrapper carries the main room's actions —
 * edit, fork, rewind, retry — every one of which acts on a thread the operator is in.
 * Nobody can type into a sub-agent, so those are not merely unused here, they are
 * offers that could not be honoured.
 *
 * **The opening prompt is shown, and it is not the operator's.** It is the task the
 * agent wrote, which is the first thing worth reading: a sub-agent that answered the
 * wrong question usually answered the question it was actually given.
 *
 * **No live tail.** A card that is still working shows the transcript as of the last
 * poll, with a line saying so, rather than attaching to the child's event stream. That
 * stream exists and would work — but a pane holding several would hold several open
 * connections to watch work nobody is blocked on, and the panel already refreshes while
 * anything is live.
 */
export function SubagentTranscript(props: { subagent: Subagent }): JSX.Element {
  const session = useChatSession(() => props.subagent.conversationId);

  return (
    <div class="border-line ml-2 flex flex-col gap-2 border-l pl-2">
      <Switch>
        <Match when={session.loading}>
          <LoadingText label="Reading the transcript…" />
        </Match>
        <Match when={session.error}>
          <Text variant="micro" tone="alert">
            That sub-agent's transcript could not be read.
          </Text>
        </Match>
        <Match when={session()}>
          {(loaded) => (
            <For each={loaded().messages}>
              {(message) => (
                <Show
                  when={message.role === "assistant"}
                  fallback={
                    <Text
                      variant="micro"
                      tone="dim"
                      class="whitespace-pre-wrap"
                    >
                      {message.content}
                    </Text>
                  }
                >
                  <TurnBlocks blocks={message.blocks} />
                </Show>
              )}
            </For>
          )}
        </Match>
      </Switch>
      <Show when={isLive(props.subagent)}>
        <Text variant="micro" tone="dim">
          Still working — this updates as it goes.
        </Text>
      </Show>
    </div>
  );
}
