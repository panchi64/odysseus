import { For, Show, type JSX } from "solid-js";
import { Frames, StatusDot, Text } from "~/ui";
import type { SubagentRun } from "../stream/fold";

/** How long a sub-agent ran, in the coarsest unit that is still true. */
function took(ms: number | undefined): string | null {
  if (ms === undefined) return null;
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

/**
 * Who the agent delegated to, and how it went.
 *
 * A delegation used to be legible only as a line of narration on its parent's tool card
 * — `_describe` flattened every frame a sub-agent produced into one string, so the
 * transcript could say *something was happening* and never which agent, on what task, or
 * whether it finished. Two of them at once were indistinguishable.
 *
 * The flattened line is still there and still wanted: it is the right thing inside a tool
 * card, which is a record of a call. This is the other consumer of the same events — a
 * roster of the work the agent handed off, which is a *state* rather than a history, and
 * so belongs beside the conversation rather than inside it.
 *
 * **A strip, not a panel.** A delegation is a row: a name, a task, and how it ended.
 * There is no document here to read at length.
 */
export function AgentsSurface(props: {
  runs: () => SubagentRun[];
  maxRows: number;
}): JSX.Element {
  const running = (): number =>
    props.runs().filter((r) => r.status === "running").length;

  return (
    <div class="flex flex-col gap-1 px-3 py-2">
      <div class="flex items-baseline justify-between gap-2">
        <Text variant="label" tone="bright">
          Agents
        </Text>
        <Text variant="micro" tone="dim">
          {running() > 0
            ? `${running()} running`
            : `${props.runs().length} done`}
        </Text>
      </div>

      <div
        class="flex flex-col gap-0.5 overflow-y-auto"
        style={{ "max-height": `${props.maxRows * 2.5}rem` }}
      >
        <For each={props.runs()}>
          {(run) => (
            <div class="flex items-start gap-2 py-0.5">
              {/* The one place colour is spent here: a failure is the thing worth
                  finding in a list of rows that otherwise all read the same. */}
              <Show
                when={run.status !== "running"}
                fallback={<Frames class="mt-0.5 shrink-0 text-info" />}
              >
                <StatusDot
                  class="mt-1 shrink-0"
                  status={run.status === "failed" ? "alert" : "nominal"}
                />
              </Show>
              <div class="flex min-w-0 flex-col">
                <div class="flex min-w-0 items-baseline gap-1.5">
                  <Text variant="label" tone="bright" class="shrink-0">
                    {run.name}
                  </Text>
                  <Text variant="micro" tone="dim" class="min-w-0 truncate">
                    {run.task}
                  </Text>
                </div>
                {/* While it runs, its latest line; once it is done, how it ended.
                    One row either way, so a finishing agent does not reflow the
                    list under whatever the operator is reading. */}
                <Text
                  variant="micro"
                  tone={run.status === "failed" ? "alert" : "dim"}
                  class="min-w-0 truncate"
                >
                  {run.status === "failed"
                    ? (run.error ?? "failed")
                    : run.status === "completed"
                      ? [took(run.durationMs), run.summary]
                          .filter(Boolean)
                          .join(" · ")
                      : (run.partial ?? "working…")}
                </Text>
              </div>
            </div>
          )}
        </For>
      </div>
    </div>
  );
}
