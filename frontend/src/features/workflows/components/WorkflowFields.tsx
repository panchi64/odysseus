import { type JSX } from "solid-js";
import { Input, Stack, Textarea } from "~/ui";
import {
  charCount,
  normalizeWorkflowName,
  WORKFLOW_ARGUMENT_HINT_MAX,
  WORKFLOW_DESCRIPTION_MAX,
  WORKFLOW_NAME_MAX,
  WORKFLOW_NAME_PATTERN,
  WORKFLOW_TITLE_MAX,
} from "../model";

/** Which fields a rejection can name. Matches the backend's own `field` strings, so a
 *  422 lands on the control it blamed rather than in a toast over the whole form. */
export type WorkflowFieldErrors = Partial<
  Record<"name" | "title" | "description" | "argument hint" | "body", string>
>;

/**
 * Everything that identifies a workflow, minus the template. Shared by the create
 * dialog and the editor's DETAILS panel so both mirror the same rules — and both defer
 * to the backend, whose message replaces the character count and renders verbatim.
 *
 * The counts never gate a submit. A frontend that refused what the server would have
 * accepted is a second rulebook, and the quieter of the two is always the one that
 * drifts.
 */
export function WorkflowFields(props: {
  name: string;
  title: string;
  description: string;
  argumentHint: string;
  onNameInput: (value: string) => void;
  onTitleInput: (value: string) => void;
  onDescriptionInput: (value: string) => void;
  onArgumentHintInput: (value: string) => void;
  errors?: WorkflowFieldErrors;
  /** The create dialog asks for a name and nothing else — everything below it is
   *  picker copy, which is easier to write once the template exists. */
  compact?: boolean;
  disabled?: boolean;
  autofocus?: boolean;
}): JSX.Element {
  // Checked against what the backend will store, not against what was typed — see
  // `normalizeWorkflowName`.
  const normalized = () => normalizeWorkflowName(props.name);
  const nameMalformed = () =>
    props.name !== "" && !WORKFLOW_NAME_PATTERN.test(normalized());
  const nameInvalid = () =>
    Boolean(props.errors?.name) ||
    props.name.length > WORKFLOW_NAME_MAX ||
    nameMalformed();
  const nameHint = () => {
    if (props.errors?.name) return props.errors.name;
    const count = charCount(props.name, WORKFLOW_NAME_MAX);
    if (nameMalformed())
      return `${count} · lowercase letters, numbers, hyphens and underscores`;
    // Said out loud rather than left as a surprise on save: the operator typed
    // "Stand Up" and will be typing "/stand-up".
    return normalized() && normalized() !== props.name
      ? `${count} · saves as /${normalized()}`
      : count;
  };

  return (
    <Stack gap={3}>
      <Input
        label="Name"
        value={props.name}
        autofocus={props.autofocus}
        disabled={props.disabled}
        invalid={nameInvalid()}
        hint={nameHint()}
        // What the operator will actually type, shown the way they will type it.
        placeholder="standup"
        onInput={(e) => props.onNameInput(e.currentTarget.value)}
      />
      {!props.compact && (
        <>
          <Input
            label="Title"
            value={props.title}
            disabled={props.disabled}
            invalid={
              Boolean(props.errors?.title) ||
              props.title.length > WORKFLOW_TITLE_MAX
            }
            hint={
              props.errors?.title ?? charCount(props.title, WORKFLOW_TITLE_MAX)
            }
            placeholder="Daily standup"
            onInput={(e) => props.onTitleInput(e.currentTarget.value)}
          />
          <Textarea
            label="Description"
            value={props.description}
            disabled={props.disabled}
            invalid={
              Boolean(props.errors?.description) ||
              props.description.length > WORKFLOW_DESCRIPTION_MAX
            }
            hint={
              props.errors?.description ??
              charCount(props.description, WORKFLOW_DESCRIPTION_MAX)
            }
            placeholder="The line under the name in the composer's menu."
            rows={3}
            onInput={(e) => props.onDescriptionInput(e.currentTarget.value)}
          />
          <Input
            label="Argument hint"
            value={props.argumentHint}
            disabled={props.disabled}
            invalid={
              Boolean(props.errors?.["argument hint"]) ||
              props.argumentHint.length > WORKFLOW_ARGUMENT_HINT_MAX
            }
            hint={
              props.errors?.["argument hint"] ??
              charCount(props.argumentHint, WORKFLOW_ARGUMENT_HINT_MAX)
            }
            placeholder="what to summarise"
            onInput={(e) => props.onArgumentHintInput(e.currentTarget.value)}
          />
        </>
      )}
    </Stack>
  );
}
