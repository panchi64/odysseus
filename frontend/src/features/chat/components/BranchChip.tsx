import { Show, createResource, createSignal, type JSX } from "solid-js";
import { Button, Modal, Stack, Text, confirm, toast } from "~/ui";
import { isApiError } from "~/lib/api";
import { refreshProjects } from "~/lib/stores/projects";
import {
  discardBranch,
  fetchBranch,
  mergeBranch,
  type BranchState,
} from "../data";

/** What a coding thread has changed, and the two ways it ends.
 *
 *  A chat thread renders nothing here — `fetchBranch` answers 404 for one, which
 *  is the ordinary case and not an error.
 *
 *  **MERGE is the operator's approval.** It is the only action in the product that
 *  writes their own checkout, which is exactly why it is a button they press and
 *  not a tool the agent can call: everything the agent does stays on a branch they
 *  can throw away, and the one step off that branch is theirs. */
export function BranchChip(props: {
  conversationId: string;
  /** Bumped by the caller when a turn completes, so the diffstat re-reads
   *  instead of showing what the thread looked like before the agent worked. */
  revision: () => number;
}): JSX.Element {
  const [branch, { refetch }] = createResource(
    () => [props.conversationId, props.revision()] as const,
    ([id]) => fetchBranch(id),
  );
  const [open, setOpen] = createSignal(false);
  const [busy, setBusy] = createSignal(false);

  const stat = (b: BranchState) => `+${b.insertions} −${b.deletions}`;

  const merge = async () => {
    setBusy(true);
    try {
      await mergeBranch(props.conversationId);
      toast.success("Merged into your working tree.");
      setOpen(false);
      void refetch();
      // The project's uncommitted count and current branch just changed.
      refreshProjects();
    } catch (err) {
      toast.error(
        isApiError(err)
          ? // A conflict is git's own message and the operator's to resolve —
            // paraphrasing it would make it less actionable, not more.
            err.detail
          : "Unable to merge this branch.",
      );
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    const ok = await confirm({
      title: "Discard this branch?",
      detail:
        "Everything the agent changed in this conversation is thrown away. Your own working tree is untouched either way.",
      confirmLabel: "Discard",
      tone: "alert",
    });
    if (!ok) return;
    setBusy(true);
    try {
      await discardBranch(props.conversationId);
      toast.success("Branch discarded.");
      setOpen(false);
      void refetch();
    } catch (err) {
      toast.error(
        isApiError(err) ? err.detail : "Unable to discard this branch.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    /* `.latest`, not `branch()`. The caller bumps `revision` the moment a turn
       settles, and a plain resource read goes undefined for the length of that
       refetch — so the chip blinked out of the header and back in at exactly the
       moment the operator looks up from a finished answer. `.latest` holds the
       previous diffstat until the new one lands, which is also the more honest
       thing to show: the branch did not stop existing while we asked about it. */
    <Show when={branch.latest}>
      {(b) => (
        <>
          {/* Sized to the chat header's other actions rather than to a toolbar
              chip — it is the third control in that row, and a shorter one
              beside them reads as a different kind of thing. */}
          <Button
            variant="ghost"
            leading="branch"
            onClick={() => setOpen(true)}
            aria-label="Review this conversation's branch"
          >
            {b().branch} · {b().filesChanged} FILE
            {b().filesChanged === 1 ? "" : "S"} {stat(b())}
          </Button>

          <Modal
            open={open()}
            onClose={() => setOpen(false)}
            title={b().branch}
            class="max-w-3xl"
          >
            <Stack gap={3}>
              <Text variant="micro" tone="dim">
                {b().filesChanged} file{b().filesChanged === 1 ? "" : "s"}{" "}
                changed against {b().baseRef} · {stat(b())}
              </Text>
              <Show
                when={b().patch}
                fallback={
                  <Text tone="dim">
                    Nothing has changed on this branch yet.
                  </Text>
                }
              >
                {/* The patch can be very wide; it scrolls inside its own box so
                    the dialog never scrolls sideways. */}
                <pre class="scrollbar-thin max-h-96 overflow-auto rounded-panel bg-raised p-3 text-code">
                  {b().patch}
                </pre>
              </Show>
              <div class="flex items-center gap-2">
                <Button
                  onClick={() => void merge()}
                  disabled={busy() || !b().filesChanged}
                >
                  Merge
                </Button>
                <Button
                  variant="danger"
                  onClick={() => void discard()}
                  disabled={busy()}
                >
                  Discard
                </Button>
                <Text variant="micro" tone="dim">
                  MERGE is the only thing that writes your own working tree.
                </Text>
              </div>
            </Stack>
          </Modal>
        </>
      )}
    </Show>
  );
}
