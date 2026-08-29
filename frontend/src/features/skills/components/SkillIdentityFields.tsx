import { type JSX } from "solid-js";
import { Input, Stack, Textarea } from "~/ui";
import {
  charCount,
  SKILL_DESCRIPTION_MAX,
  SKILL_NAME_MAX,
  SKILL_NAME_PATTERN,
} from "../model";

/** Which fields a rejection can name. */
export type SkillFieldErrors = Partial<Record<"name" | "description", string>>;

/** The two fields that identify a skill, with live character counts. Shared by
 *  the create dialog and the editor's DETAILS panel so both mirror the same
 *  rules — and both defer to the backend, whose 422 message replaces the count
 *  and renders verbatim. The counts never gate a submit: the server decides. */
export function SkillIdentityFields(props: {
  name: string;
  description: string;
  onNameInput: (value: string) => void;
  onDescriptionInput: (value: string) => void;
  /** Field-scoped messages from the backend, rendered as-is. */
  errors?: SkillFieldErrors;
  descriptionRows?: number;
  disabled?: boolean;
  autofocus?: boolean;
}): JSX.Element {
  const nameMalformed = () =>
    props.name !== "" && !SKILL_NAME_PATTERN.test(props.name);
  const nameInvalid = () =>
    Boolean(props.errors?.name) ||
    props.name.length > SKILL_NAME_MAX ||
    nameMalformed();
  const nameHint = () => {
    if (props.errors?.name) return props.errors.name;
    const count = charCount(props.name, SKILL_NAME_MAX);
    return nameMalformed()
      ? `${count} · lowercase letters, numbers, and hyphens only`
      : count;
  };

  const descriptionInvalid = () =>
    Boolean(props.errors?.description) ||
    props.description.length > SKILL_DESCRIPTION_MAX;
  const descriptionHint = () =>
    props.errors?.description ??
    charCount(props.description, SKILL_DESCRIPTION_MAX);

  return (
    <Stack gap={3}>
      <Input
        label="Name"
        value={props.name}
        autofocus={props.autofocus}
        disabled={props.disabled}
        invalid={nameInvalid()}
        hint={nameHint()}
        placeholder="summarize-document"
        onInput={(e) => props.onNameInput(e.currentTarget.value)}
      />
      <Textarea
        label="Description"
        value={props.description}
        disabled={props.disabled}
        invalid={descriptionInvalid()}
        hint={descriptionHint()}
        placeholder="What this skill does and when the agent should reach for it."
        rows={props.descriptionRows ?? 3}
        onInput={(e) => props.onDescriptionInput(e.currentTarget.value)}
      />
    </Stack>
  );
}
