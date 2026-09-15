import { createEffect, createSignal, on, Show, type JSX } from "solid-js";
import { createStore } from "solid-js/store";
import {
  Button,
  EditorShell,
  EmptyState,
  Panel,
  Stack,
  StatusFlag,
  Text,
  Textarea,
  toast,
} from "~/ui";
import { timestamp } from "~/lib/format";
import { settled } from "~/lib/resource";
import {
  updateWorkflow,
  useWorkflows,
  workflowErrorField,
  workflowErrorMessage,
} from "../data";
import {
  charCount,
  workflowStatusFlag,
  workflowStatusLabel,
  WORKFLOW_BODY_MAX,
  type Workflow,
} from "../model";
import {
  WorkflowFields,
  type WorkflowFieldErrors,
} from "../components/WorkflowFields";

interface WorkflowDraft {
  name: string;
  title: string;
  description: string;
  argumentHint: string;
  body: string;
}

function draftOf(workflow: Workflow): WorkflowDraft {
  return {
    name: workflow.name,
    title: workflow.title,
    description: workflow.description,
    argumentHint: workflow.argumentHint ?? "",
    body: workflow.body,
  };
}

/**
 * The template in the main column, everything the picker shows in the aside.
 *
 * **Read out of the list rather than fetched on its own.** A workflow is four short
 * fields and a template; the list already ships all of it, so a `GET` per open would be
 * a second round trip for bytes this screen is holding. That is only true because there
 * is no summary/detail split to go stale — the moment one exists, this becomes a real
 * detail resource like the skill editor's.
 */
export function WorkflowEditorScreen(props: {
  id: string;
  onBack: () => void;
}): JSX.Element {
  const workflowsResource = useWorkflows();
  // `settled`, not a bare `.latest`: reading an unresolved resource inside a tracked
  // scope registers with the nearest Suspense, and this screen has none of its own — the
  // dialog's would swap the pane out from under an open editor on every refetch.
  const workflow = (): Workflow | undefined =>
    settled(workflowsResource)?.find((w) => w.id === props.id);
  const loadError = (): string | null =>
    workflowsResource.error
      ? workflowErrorMessage(
          workflowsResource.error,
          "Could not load this workflow.",
        )
      : null;

  const [draft, setDraft] = createStore<WorkflowDraft>({
    name: "",
    title: "",
    description: "",
    argumentHint: "",
    body: "",
  });
  const [snapshot, setSnapshot] = createSignal("");
  const [errors, setErrors] = createSignal<WorkflowFieldErrors>({});
  const [showSaved, setShowSaved] = createSignal(false);
  const [busy, setBusy] = createSignal(false);

  // Seed the draft once the workflow resolves. Reset when the id changes so a reused
  // editor instance doesn't keep the previous one's draft.
  //
  // A **signal**, not a plain `let`, and that is load-bearing rather than tidy. Effects
  // run after render, so this is still false when the SAVE button's `disabled` binding
  // first evaluates — and `seeded && …` short-circuits, so that binding would subscribe
  // to nothing at all and never re-run, leaving SAVE disabled no matter what is typed.
  // Reading a signal registers the dependency even when the rest is short-circuited past.
  const [seeded, setSeeded] = createSignal(false);
  createEffect(
    on(
      () => props.id,
      () => {
        setSeeded(false);
        setSnapshot("");
        setErrors({});
      },
      { defer: true },
    ),
  );
  createEffect(() => {
    const w = workflow();
    if (seeded() || !w) return;
    const init = draftOf(w);
    setDraft(init);
    setSnapshot(JSON.stringify(init));
    setSeeded(true);
  });

  // A plain thunk, deliberately **not** a `createMemo` — which is the obvious-looking
  // change and breaks the SAVE button. Spreading a store inside a memo leaves it with no
  // registered dependency to invalidate on, so it computes once, `isDirty()` stays false
  // forever, and the button never re-enables no matter what is typed. Re-stringifying
  // five short fields per read costs nothing; the skill editor next door does the same.
  const currentJson = () => JSON.stringify({ ...draft });
  const isDirty = () => seeded() && currentJson() !== snapshot();

  async function handleSave(): Promise<void> {
    if (!isDirty() || busy()) return;
    setBusy(true);
    setErrors({});
    try {
      const saved = await updateWorkflow(props.id, {
        name: draft.name,
        title: draft.title,
        description: draft.description,
        argumentHint: draft.argumentHint,
        body: draft.body,
      });
      // Re-snapshot from what came back, so the editor is clean against what the backend
      // actually stored rather than what was typed at it — a name is normalised on the
      // way in, and the operator should see the normalised one.
      const next = draftOf(saved);
      setDraft(next);
      setSnapshot(JSON.stringify(next));
      setShowSaved(true);
      toast.success("Workflow saved");
      setTimeout(() => setShowSaved(false), 2000);
    } catch (err) {
      const message = workflowErrorMessage(err, "Could not save the workflow.");
      const field = workflowErrorField(err);
      if (
        field === "name" ||
        field === "title" ||
        field === "description" ||
        field === "argument hint" ||
        field === "body"
      ) {
        setErrors({ [field]: message });
      } else {
        toast.error(message);
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleEnabledToggle(): Promise<void> {
    const current = workflow();
    if (!current) return;
    const next = !current.enabled;
    try {
      await updateWorkflow(props.id, { enabled: next });
      toast.success(
        next
          ? "Back in the menu."
          : "Out of the menu — still here, not offered.",
      );
    } catch (err) {
      toast.error(
        workflowErrorMessage(
          err,
          `Could not turn this workflow ${next ? "on" : "off"}.`,
        ),
      );
    }
  }

  const toolsPanel = () => (
    <>
      <Panel label="Details">
        <WorkflowFields
          name={draft.name}
          title={draft.title}
          description={draft.description}
          argumentHint={draft.argumentHint}
          onNameInput={(v) => setDraft("name", v)}
          onTitleInput={(v) => setDraft("title", v)}
          onDescriptionInput={(v) => setDraft("description", v)}
          onArgumentHintInput={(v) => setDraft("argumentHint", v)}
          errors={errors()}
          disabled={busy()}
        />
      </Panel>

      <Panel label="Actions">
        <Button
          variant="default"
          size="sm"
          leading="check"
          block
          onClick={() => void handleEnabledToggle()}
        >
          {workflow()?.enabled
            ? "Take out of the menu"
            : "Put back in the menu"}
        </Button>
      </Panel>
    </>
  );

  return (
    <Show
      when={workflow()}
      fallback={
        <EmptyState
          icon="terminal"
          message={loadError() ? "Workflow unavailable" : "Workflow not found"}
          hint={loadError() ?? "The requested workflow does not exist."}
          action={
            <Button
              variant="default"
              leading="chevron-left"
              onClick={props.onBack}
            >
              Back to workflows
            </Button>
          }
        />
      }
    >
      {(w) => (
        <EditorShell
          onBack={props.onBack}
          backLabel="Back to workflows"
          title={draft.name ? `/${draft.name}` : "—"}
          dirty={isDirty()}
          meta={
            <Text variant="micro" tone="dim">
              {charCount(draft.body, WORKFLOW_BODY_MAX)} · UPDATED{" "}
              {timestamp(w().updatedAt)}
            </Text>
          }
          status={
            <StatusFlag status={workflowStatusFlag(w().enabled)}>
              {workflowStatusLabel(w().enabled)}
            </StatusFlag>
          }
          actions={
            <Button
              variant={showSaved() ? "default" : "primary"}
              leading={showSaved() ? "check" : "download"}
              size="sm"
              disabled={!isDirty() || busy()}
              onClick={() => void handleSave()}
            >
              {showSaved() ? "Saved" : "Save"}
            </Button>
          }
          aside={toolsPanel}
        >
          <Stack gap={2} class="h-full">
            <Text variant="micro" tone="dim">
              This goes in front of the model for the turn it is invoked on, and
              is not kept in the conversation afterwards — so editing it changes
              what the next invocation does rather than rewriting history.
            </Text>
            <Textarea
              value={draft.body}
              onInput={(e) => setDraft("body", e.currentTarget.value)}
              rows={28}
              class="h-full w-full resize-none font-mono text-body"
            />
          </Stack>
        </EditorShell>
      )}
    </Show>
  );
}
