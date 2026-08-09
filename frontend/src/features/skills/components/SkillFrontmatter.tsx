import { For, Show, type JSX } from "solid-js";
import { Chip, Field, InfoHint, Row, Stack, Text } from "~/ui";
import type { Skill } from "../model";

/** The frontmatter the operator doesn't edit here: provenance, licensing, the
 *  advisory tool list, and any non-standard keys the bundle carried. All
 *  read-only — `extras` in particular is preserved verbatim so an export is
 *  lossless, which editing through a form would quietly break. */
export function SkillFrontmatter(props: { skill: Skill }): JSX.Element {
  const extras = () => Object.entries(props.skill.extras ?? {});

  return (
    <Stack gap={3}>
      <Field
        label="SOURCE"
        orientation="row"
        value={props.skill.source.toUpperCase()}
      />
      <Show when={props.skill.license}>
        <Field label="LICENSE" orientation="row" value={props.skill.license} />
      </Show>
      <Show when={props.skill.compatibility}>
        <Field
          label="COMPATIBILITY"
          orientation="row"
          value={props.skill.compatibility}
        />
      </Show>

      <Show when={props.skill.allowedTools?.length}>
        <Stack gap={1}>
          <Row align="center" gap={1}>
            <Text variant="label" tone="dim">
              ALLOWED TOOLS · ADVISORY
            </Text>
            <InfoHint label="Advisory only. This list is what the bundle's author declared the skill uses — it is recorded and displayed, never enforced. It grants nothing and restricts nothing." />
          </Row>
          <Row gap={1} wrap>
            <For each={props.skill.allowedTools ?? []}>
              {(tool) => <Chip>{tool}</Chip>}
            </For>
          </Row>
        </Stack>
      </Show>

      <Show when={extras().length}>
        <Stack gap={1}>
          <Row align="center" gap={1}>
            <Text variant="label" tone="dim">
              PRESERVED KEYS
            </Text>
            <InfoHint label="Non-standard frontmatter this bundle arrived with. It's kept as-is so exporting returns the bundle unchanged, and it isn't editable here." />
          </Row>
          <For each={extras()}>
            {([key, value]) => (
              <Field
                label={key.toUpperCase()}
                tone="dim"
                value={
                  typeof value === "string" ? value : JSON.stringify(value)
                }
              />
            )}
          </For>
        </Stack>
      </Show>
    </Stack>
  );
}
