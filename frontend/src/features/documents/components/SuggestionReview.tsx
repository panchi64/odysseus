import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  EmptyState,
  LoadingText,
  Panel,
  Row,
  Stack,
  Text,
  toast,
} from "~/ui";
import { isApiError } from "~/lib/api";
import { timestamp } from "~/lib/format";
import {
  acceptAllSuggestions,
  acceptSuggestion,
  rejectSuggestion,
  useDocumentSuggestions,
} from "../data";
import { lineDiff } from "../diff";
import { DocumentDiff } from "./DocumentDiff";
import type {
  SuggestionChange,
  SuggestionOutcome,
  SuggestionSet,
} from "../model";

/** Change-by-change review of what the AI has proposed (`DOC-3`).
 *
 *  Nothing here decides anything: the backend owns whether a change can still be applied,
 *  what version accepting mints, and what the document says afterwards. This renders the
 *  pending sets and relays ACCEPT / REJECT / ACCEPT ALL, then hands the resulting body up
 *  so whoever owns the editing surface can adopt it.
 *
 *  A change is shown as a diff of just its own span (old → new) rather than of the whole
 *  document — the operator is deciding on *this* change, so that is what they read. */
export function SuggestionReview(props: {
  documentId: string;
  /** Called with the backend's resulting body after any accept, so the host screen can
   *  re-seed its draft instead of sitting on a stale one. */
  onApplied?: (outcome: SuggestionOutcome) => void;
}): JSX.Element {
  const sets = useDocumentSuggestions(() => props.documentId);
  // Ids currently in flight, so a change can't be double-decided by a double click.
  const [busy, setBusy] = createSignal<string[]>([]);
  const isBusy = (id: string): boolean => busy().includes(id);

  async function guard<T>(
    id: string,
    run: () => Promise<T>,
  ): Promise<T | null> {
    if (isBusy(id)) return null;
    setBusy((prev) => [...prev, id]);
    try {
      return await run();
    } catch (err) {
      // 409 is the backend refusing a change whose text has moved — the one failure the
      // operator can act on, so it gets the backend's own words rather than a generic one.
      toast.error(
        isApiError(err) && err.status === 409
          ? err.detail
          : "Could not apply that change",
      );
      return null;
    } finally {
      setBusy((prev) => prev.filter((x) => x !== id));
    }
  }

  function report(outcome: SuggestionOutcome): void {
    props.onApplied?.(outcome);
    if (outcome.skipped.length)
      toast.error(
        `${outcome.skipped.length} change${outcome.skipped.length === 1 ? "" : "s"} no longer ` +
          "match the document and were left for review",
      );
  }

  async function handleAccept(change: SuggestionChange): Promise<void> {
    const outcome = await guard(change.id, () =>
      acceptSuggestion(props.documentId, change.id),
    );
    if (!outcome) return;
    report(outcome);
    toast.success(`Applied as version ${outcome.version}`);
  }

  async function handleReject(change: SuggestionChange): Promise<void> {
    const done = await guard(change.id, async () => {
      await rejectSuggestion(props.documentId, change.id);
      return true;
    });
    if (done) toast.success("Change rejected");
  }

  async function handleAcceptAll(set: SuggestionSet): Promise<void> {
    const outcome = await guard(set.id, () =>
      acceptAllSuggestions(props.documentId, set.id),
    );
    if (!outcome) return;
    report(outcome);
    if (outcome.accepted.length)
      toast.success(
        `Applied ${outcome.accepted.length} changes as version ${outcome.version}`,
      );
  }

  const total = (): number =>
    (sets() ?? []).reduce((sum, set) => sum + set.pending, 0);

  return (
    <Panel
      label="AI suggestions"
      meta={
        <Text variant="micro" tone="dim" class="tabular-nums">
          {total()}
        </Text>
      }
    >
      <Suspense fallback={<LoadingText label="Loading suggestions" />}>
        <Show
          when={(sets() ?? []).length}
          fallback={
            <EmptyState
              icon="check"
              message="Nothing proposed"
              hint="Changes the AI proposes in chat show up here to accept or reject."
            />
          }
        >
          <Stack gap={4}>
            <For each={sets()}>
              {(set) => (
                <Stack gap={2}>
                  <Row gap={3} align="center" justify="between">
                    <Text variant="micro" tone="dim">
                      {set.summary || "Proposed changes"} ·{" "}
                      {timestamp(set.createdAt)}
                    </Text>
                    <Button
                      variant="primary"
                      size="sm"
                      leading="check"
                      disabled={isBusy(set.id)}
                      onClick={() => void handleAcceptAll(set)}
                    >
                      Accept all
                    </Button>
                  </Row>
                  <For each={set.changes.filter((c) => c.status === "pending")}>
                    {(change) => (
                      <ChangeCard
                        change={change}
                        busy={isBusy(change.id) || isBusy(set.id)}
                        onAccept={() => void handleAccept(change)}
                        onReject={() => void handleReject(change)}
                      />
                    )}
                  </For>
                </Stack>
              )}
            </For>
          </Stack>
        </Show>
      </Suspense>
    </Panel>
  );
}

/** One proposed change: its rationale, the span it would rewrite, and the two controls
 *  that decide it. */
function ChangeCard(props: {
  change: SuggestionChange;
  busy: boolean;
  onAccept: () => void;
  onReject: () => void;
}): JSX.Element {
  const result = () => lineDiff(props.change.oldText, props.change.newText);
  return (
    <Stack gap={2} class="rounded-panel bg-surface p-2 shadow-1">
      <Show when={props.change.explanation}>
        <Text variant="body" tone="dim">
          {props.change.explanation}
        </Text>
      </Show>
      <DocumentDiff result={result()} />
      <Row gap={2}>
        <Button
          variant="primary"
          size="sm"
          leading="check"
          disabled={props.busy}
          onClick={props.onAccept}
        >
          Accept
        </Button>
        <Button
          variant="ghost"
          size="sm"
          leading="close"
          disabled={props.busy}
          onClick={props.onReject}
        >
          Reject
        </Button>
      </Row>
    </Stack>
  );
}
