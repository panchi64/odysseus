import { Show, type JSX } from "solid-js";
import { Text } from "~/ui";
import type { WorkStep } from "../workShape";
import { ProcessRow, Sep } from "./ProcessRow";

/** The collapsed work log's latest step, hung off the header by an elbow.
 *
 *  The header says *why* the run is doing what it does (the model's narration);
 *  this row says *what* it last did. It is an ordinary `ProcessRow` with nothing
 *  to open, so it speaks the rows' own `glyph · Label · detail` anatomy and keeps
 *  their truncation rules by construction rather than by copy. Splitting reason
 *  from act is what lets each be read at a glance: a single line carrying both
 *  truncated the reason, which is the half worth reading.
 *
 *  It only exists while the log is shut. Open, the same step is the last row of
 *  the list, and a second copy of it directly above the first would be noise.
 *
 *  **It arrives by tracing in** (`.ody-trace-*`, §8): the elbow draws itself down
 *  and across, and the row resolves as the stroke reaches it. The caller keys it
 *  on the step's block id, so each step the run folds in replays the arrival —
 *  the fold's proof of life — while a re-render of the same step does not.
 *
 *  The elbow sits in the chevron slot `ProcessRow` holds open on a row with
 *  nothing to reveal — centred under the header's own chevron (`px-2` plus half
 *  its 12px glyph) — so the branch visibly hangs off the control that opens the
 *  fold, and the glyph lands where the header's label begins.
 *
 *  **It reads as a schematic, not a list item** — the mission-control register
 *  (§9, §10.14). The glyph sits in a hard-cornered socket and the elbow runs all
 *  the way to its edge, so the stroke is a trace landing on a pin rather than a
 *  line that stops short of an icon. The socket blips the info tone as the trace
 *  reaches it and snaps back (`.ody-trace-pin`, stepped — the machine register),
 *  and the label is the machine's `meta` voice: this row reports what the run
 *  last did, it is not a thing to open. */
export function WorkLogLatest(props: { step: WorkStep }): JSX.Element {
  return (
    <div class="relative">
      {/* From the header's chevron centre (`left-3.5`) to the glyph's socket
          (`px-2` + the 12px chevron slot + `gap-2` = 28px). */}
      <span
        aria-hidden="true"
        class="pointer-events-none absolute inset-y-0 left-3.5 w-3.5"
      >
        <span class="ody-trace-down absolute top-0 left-0 h-1/2 w-px bg-line" />
        <span class="ody-trace-across absolute top-1/2 left-0 h-px w-full bg-line" />
      </span>
      <ProcessRow
        class="ody-trace-body"
        open={false}
        foldable={false}
        onToggle={() => {}}
        icon={props.step.icon}
        iconClass="ody-trace-pin box-content border border-line p-0.5 text-dim"
        label={props.step.label}
        labelVariant="meta"
      >
        <Show when={props.step.detail}>
          {(detail) => (
            <>
              <Sep />
              <Text variant="micro" tone="dim" class="min-w-0 truncate">
                {detail()}
              </Text>
            </>
          )}
        </Show>
      </ProcessRow>
    </div>
  );
}
