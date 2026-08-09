import {
  createEffect,
  createSignal,
  on,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import { createStore } from "solid-js/store";
import {
  Button,
  EditorShell,
  EmptyState,
  LoadingText,
  Panel,
  Stack,
  StatusFlag,
  Text,
  Textarea,
  toast,
} from "~/ui";
import { bytes, timestamp } from "~/lib/format";
import {
  exportSkill,
  setSkillPublished,
  skillErrorField,
  skillErrorMessage,
  updateSkill,
  useSkillDetail,
} from "../data";
import {
  skillSourceFlag,
  skillStatusFlag,
  skillStatusLabel,
  type Skill,
} from "../model";
import { SkillBundlePanel } from "../components/SkillBundlePanel";
import { SkillFrontmatter } from "../components/SkillFrontmatter";
import {
  SkillIdentityFields,
  type SkillFieldErrors,
} from "../components/SkillIdentityFields";

interface SkillDraft {
  name: string;
  description: string;
  body: string;
}

function draftOf(skill: Skill): SkillDraft {
  return {
    name: skill.name,
    description: skill.description,
    body: skill.body,
  };
}

/** Full-page skill editor — the `SKILL.md` body in the main column, the fields
 *  that identify it and the rest of the bundle in the tools aside. Every rule
 *  about what's valid lives in the backend; a rejection here renders exactly
 *  what it said, on the field it named. */
export function SkillEditorScreen(props: { id: string }): JSX.Element {
  const skillResource = useSkillDetail(() => props.id);
  // Reading the accessor re-throws a load failure, and there is no ErrorBoundary in this
  // app — a 500 would blank the editor entirely. `.latest`/`.error` degrade it to the
  // not-found panel, which carries the backend's own message.
  const skill = () =>
    skillResource.error ? undefined : (skillResource.latest ?? undefined);
  const loadError = (): string | null =>
    skillResource.error
      ? skillErrorMessage(skillResource.error, "Could not load this skill.")
      : null;

  const [draft, setDraft] = createStore<SkillDraft>({
    name: "",
    description: "",
    body: "",
  });
  const [snapshot, setSnapshot] = createSignal("");
  const [errors, setErrors] = createSignal<SkillFieldErrors>({});
  const [showSaved, setShowSaved] = createSignal(false);
  const [busy, setBusy] = createSignal(false);

  // Seed the draft once the skill resolves. Reset when the id changes so a reused
  // editor instance doesn't keep the previous skill's draft.
  let seeded = false;
  createEffect(
    on(
      () => props.id,
      () => {
        seeded = false;
        setSnapshot("");
        setErrors({});
      },
      { defer: true },
    ),
  );
  createEffect(() => {
    const s = skill();
    if (seeded || !s) return;
    seeded = true;
    const init = draftOf(s);
    setDraft(init);
    setSnapshot(JSON.stringify(init));
  });

  const currentJson = () => JSON.stringify({ ...draft });
  const isDirty = () => seeded && currentJson() !== snapshot();

  /** Returns whether the working copy is now persisted — PUBLISH depends on knowing. */
  async function handleSave(): Promise<boolean> {
    if (!isDirty() || busy()) return !isDirty();
    setBusy(true);
    setErrors({});
    try {
      const saved = await updateSkill(props.id, {
        name: draft.name,
        description: draft.description,
        body: draft.body,
      });
      // Re-snapshot from what came back, so the editor is clean against what the
      // backend actually stored rather than what was typed at it.
      const next = draftOf(saved);
      setDraft(next);
      setSnapshot(JSON.stringify(next));
      setShowSaved(true);
      toast.success("Skill saved");
      setTimeout(() => setShowSaved(false), 2000);
      return true;
    } catch (err) {
      const message = skillErrorMessage(err, "Could not save the skill.");
      const field = skillErrorField(err);
      if (field === "name" || field === "description") {
        setErrors({ [field]: message });
      } else {
        toast.error(message);
      }
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function handlePublishToggle(): Promise<void> {
    const current = skill();
    if (!current) return;
    const next = !current.published;
    try {
      // Publish what's on screen, not what was last saved. Without this, PUBLISH ships the
      // stale body while the editor still shows the operator's unsaved rewrite — and the
      // backend's empty-body guard is evaluated against that stale body too.
      if (isDirty()) {
        const saved = await handleSave();
        if (!saved) return;
      }
      await setSkillPublished(props.id, next);
      toast.success(
        next
          ? "Published — the agent can see this skill now."
          : "Unpublished — back to draft.",
      );
    } catch (err) {
      toast.error(
        skillErrorMessage(
          err,
          `Could not ${next ? "publish" : "unpublish"} the skill.`,
        ),
      );
    }
  }

  async function handleExport(): Promise<void> {
    const current = skill();
    if (!current) return;
    try {
      await exportSkill(current.id, current.name);
    } catch (err) {
      toast.error(skillErrorMessage(err, "Could not export the skill."));
    }
  }

  const toolsPanel = () => (
    <>
      <Panel label="DETAILS">
        <Stack gap={4}>
          <SkillIdentityFields
            name={draft.name}
            description={draft.description}
            onNameInput={(v) => setDraft("name", v)}
            onDescriptionInput={(v) => setDraft("description", v)}
            errors={errors()}
            disabled={busy()}
          />
          <Show when={skill()}>{(s) => <SkillFrontmatter skill={s()} />}</Show>
        </Stack>
      </Panel>

      <Panel label="ACTIONS">
        <Stack gap={2}>
          <Button
            variant="default"
            size="sm"
            leading="check"
            block
            onClick={() => void handlePublishToggle()}
          >
            {skill()?.published ? "UNPUBLISH" : "PUBLISH"}
          </Button>
          <Button
            variant="default"
            size="sm"
            leading="download"
            block
            onClick={() => void handleExport()}
          >
            EXPORT BUNDLE
          </Button>
        </Stack>
      </Panel>

      <Show when={skill()}>
        {(s) => <SkillBundlePanel skillId={s().id} files={s().files} />}
      </Show>
    </>
  );

  return (
    <Suspense fallback={<LoadingText label="LOADING SKILL" />}>
      <Show
        when={skill()}
        fallback={
          <EmptyState
            icon="layers"
            message={loadError() ? "SKILL UNAVAILABLE" : "SKILL NOT FOUND"}
            hint={loadError() ?? "The requested skill does not exist."}
            action={
              <Button variant="default" leading="chevron-left" href="/skills">
                BACK TO SKILLS
              </Button>
            }
          />
        }
      >
        {(s) => (
          <EditorShell
            backHref="/skills"
            backLabel="BACK TO SKILLS"
            title={draft.name || "—"}
            dirty={isDirty()}
            meta={
              <Text variant="micro" tone="dim">
                {s().fileCount} FILES · {bytes(s().sizeBytes)} · UPDATED{" "}
                {timestamp(s().updatedAt)}
              </Text>
            }
            status={
              <>
                <Show when={s().source !== "authored"}>
                  <StatusFlag status={skillSourceFlag[s().source]}>
                    {s().source.toUpperCase()}
                  </StatusFlag>
                </Show>
                <StatusFlag status={skillStatusFlag(s().published)}>
                  {skillStatusLabel(s().published)}
                </StatusFlag>
              </>
            }
            actions={
              <Button
                variant={showSaved() ? "default" : "primary"}
                leading={showSaved() ? "check" : "download"}
                size="sm"
                disabled={!isDirty() || busy()}
                onClick={() => void handleSave()}
              >
                {showSaved() ? "SAVED" : "SAVE"}
              </Button>
            }
            aside={toolsPanel}
          >
            <Textarea
              value={draft.body}
              onInput={(e) => setDraft("body", e.currentTarget.value)}
              rows={32}
              class="h-full w-full resize-none font-mono text-body"
            />
          </EditorShell>
        )}
      </Show>
    </Suspense>
  );
}
