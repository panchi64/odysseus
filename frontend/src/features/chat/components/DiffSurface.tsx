import { Show, createSignal, type JSX } from "solid-js";
import { Button, DiffView, EmptyState, Text, confirm, toast } from "~/ui";
import { isApiError } from "~/lib/api";
import { refreshProjects } from "~/lib/stores/projects";
import { discardBranch, mergeBranch, type BranchState } from "../data";

/**
 * What a code thread has changed, and the two ways it ends.
 *
 * This was a modal over a raw `<pre>`, opened from the header chip. Two things were
 * wrong with that. A patch is something you read *against* the conversation that
 * produced it — a dialog covers the very transcript you are checking it against — and
 * a unified diff rendered as preformatted text is the one thing in the product with a
 * purpose-built renderer sitting unused three files away.
 *
 * **MERGE is the operator's approval.** It is the only action in the product that
 * writes their own checkout, which is exactly why it is a button they press and not a
 * tool the agent can call: everything the agent does stays on a branch they can throw
 * away, and the one step off that branch is theirs. Moving the patch into a pane does
 * not move that decision — the buttons come with it.
 */
export function DiffSurface(props: {
  branch: () => BranchState | null | undefined;
  onChanged: () => void;
  fontStep?: number;
  softWrap?: boolean;
}): JSX.Element {
  const [busy, setBusy] = createSignal(false);

  const stat = (b: BranchState): string => `+${b.insertions} −${b.deletions}`;

  const merge = async (b: BranchState): Promise<void> => {
    setBusy(true);
    try {
      await mergeBranch(b.conversationId);
      toast.success("Merged into your working tree.");
      props.onChanged();
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

  const discard = async (b: BranchState): Promise<void> => {
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
      await discardBranch(b.conversationId);
      toast.success("Branch discarded.");
      props.onChanged();
    } catch (err) {
      toast.error(
        isApiError(err) ? err.detail : "Unable to discard this branch.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Show
      when={props.branch()}
      fallback={
        <EmptyState
          icon="branch"
          message="No branch"
          hint="Only a code thread works on a branch of its own."
        />
      }
    >
      {(b) => (
        <div class="flex h-full min-h-0 flex-col">
          <div class="flex items-center justify-between gap-2 px-3 py-2">
            <Text variant="micro" tone="dim" class="min-w-0 truncate">
              {b().filesChanged} file{b().filesChanged === 1 ? "" : "s"} against{" "}
              {b().baseRef} · {stat(b())}
            </Text>
          </div>

          <div class="min-h-0 flex-1">
            <Show
              when={b().patch}
              fallback={
                <EmptyState
                  icon="branch"
                  message="Nothing changed yet"
                  hint="The agent has not written anything on this branch."
                />
              }
            >
              <DiffView
                diff={b().patch}
                fontStep={props.fontStep}
                softWrap={props.softWrap}
                class="h-full"
              />
            </Show>
          </div>

          {/* The two endings, at the bottom where a decision belongs — after the
              thing being decided about, not above it. */}
          <div class="flex shrink-0 flex-wrap items-center gap-2 px-3 py-2">
            <Button
              onClick={() => void merge(b())}
              disabled={busy() || !b().filesChanged}
            >
              Merge
            </Button>
            <Button
              variant="danger"
              onClick={() => void discard(b())}
              disabled={busy()}
            >
              Discard
            </Button>
            <Text variant="micro" tone="dim">
              MERGE is the only thing that writes your own working tree.
            </Text>
          </div>
        </div>
      )}
    </Show>
  );
}
