import { Show, type JSX } from "solid-js";
import { Frames, Icon, Text } from "~/ui";
import { compactCount } from "~/lib/format";
import { compactionReasonCause } from "../compactionReason";
import type { CompactionProgress } from "../model";
import { Sep } from "./ProcessRow";

/** The pause where the chassis folded this thread's history, on the turn's own rail.
 *
 *  **It shares the rail's anatomy and refuses both the card and the chevron.** Like an
 *  injected context block it sits flat on the page rather than on a raised `bg-surface`
 *  panel, because the model neither did this nor asked for it — we did it to the model.
 *  Unlike every other row here it has nothing to expand: the summary that comes out of
 *  the fold is the divider's to show, and a chevron opening onto nothing is a control
 *  that lies. So it is a plain row, not a `ProcessRow`, and borrows only its `Sep`.
 *
 *  **Its whole reason for existing is the wait.** Summarizing a long thread is a model
 *  call of its own — tens of seconds during which the turn produces nothing — and
 *  without a row the operator watches a stall and reads it as one. So the row appears
 *  while it runs, throbbing, and stays afterwards as the record of where in the turn
 *  the fold happened; the divider above records what it cost. The reason is spelled out
 *  because "the window filled" and "the provider refused the request" are not the same
 *  thing to have happened, and only the second one means the turn nearly died.
 *
 *  The trailing figure is what is going *into* the fold, in the slot a tool call spends
 *  on elapsed time — the same coarse estimate the context gauge renders, and marked `~`
 *  for the same reason. */
export function CompactionProgressCard(props: {
  compaction: CompactionProgress;
}): JSX.Element {
  const c = () => props.compaction;
  return (
    <div class="flex w-full items-center justify-between gap-2 pr-1.5">
      <div class="flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5">
        {/* The glyph is the fold itself; the throbber replaces it while the summarizer
            runs, so "working" reads from the same position the kind reads from. */}
        <Show
          when={c().done}
          fallback={<Frames class="text-micro shrink-0 text-info" />}
        >
          <Icon name="layers" size={12} class="shrink-0 text-dim" />
        </Show>
        <Text
          variant="label"
          tone="bright"
          class="max-w-[45%] shrink-0 truncate"
        >
          {c().done ? "Context compacted" : "Compacting context"}
        </Text>
        <Sep />
        <Text variant="micro" tone="dim" class="min-w-0 truncate">
          because {compactionReasonCause(c().reason)}
        </Text>
        {/* Guarded on `> 0`: a fold the backend reports nothing about should print no
            count at all rather than "0 messages", which reads as a fold that did
            nothing. */}
        <Show when={c().messages > 0}>
          <Sep />
          <Text variant="micro" tone="dim" class="min-w-0 shrink-0">
            {c().messages} {c().messages === 1 ? "message" : "messages"}
          </Text>
        </Show>
      </div>
      <Show when={c().tokensEstimate > 0}>
        <Text variant="micro" tone="dim" class="shrink-0 pr-1 tabular-nums">
          ~{compactCount(c().tokensEstimate, true)}
        </Text>
      </Show>
    </div>
  );
}
