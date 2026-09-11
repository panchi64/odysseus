import { Show, type JSX } from "solid-js";
import { Button } from "~/ui";
import type { BranchState } from "../data";

/**
 * What a code thread has changed, as a readout you can open.
 *
 * A sandbox thread renders nothing here — the branch read answers 404 for one, which is
 * the ordinary case and not an error.
 *
 * **It no longer owns the patch.** The chip used to fetch the branch itself and show the
 * diff in a modal over a raw `<pre>`. Both were wrong once the panel could hold a diff:
 * a patch is read *against* the conversation that produced it, and a dialog covers the
 * very transcript you are checking it against. So the chip is what it always looked
 * like — a diffstat — and pressing it opens the Changes surface beside the thread. The
 * merge and discard buttons went with the patch, because they are decisions about the
 * thing you are looking at.
 *
 * The fetch moved out too (`branchState.ts`), since the surface and the chip are two
 * views of one answer.
 */
export function BranchChip(props: {
  branch: () => BranchState | null | undefined;
  onOpen: () => void;
}): JSX.Element {
  return (
    <Show when={props.branch()}>
      {(b) => (
        /* Sized to the chat header's other actions rather than to a toolbar chip —
           it is a control in that row, and a shorter one beside them reads as a
           different kind of thing. */
        <Button
          variant="ghost"
          leading="branch"
          onClick={props.onOpen}
          aria-label="Review this conversation's changes"
        >
          {b().branch} · {b().filesChanged} FILE
          {b().filesChanged === 1 ? "" : "S"} +{b().insertions} −{b().deletions}
        </Button>
      )}
    </Show>
  );
}
