import { Show, createMemo, type JSX } from "solid-js";
import { Combobox, Select, Text } from "~/ui";
import { useProjects } from "~/lib/stores/projects";

/** CHAT or CODING for the *next* conversation, plus which project a coding thread
 *  works in.
 *
 *  Shown only while the thread is still unsaved. A thread's mode and project are
 *  set at creation and never again — a coding thread owns a git branch, and
 *  re-pointing it mid-flight would strand that branch and leave the transcript
 *  describing a tree that isn't there. So this disappears the moment the first
 *  message lands, and an existing coding thread shows its branch instead.
 *
 *  Presentation only: it captures the operator's choice and hands it to the send
 *  path, which passes it to the backend once. Nothing here decides anything —
 *  including whether the choice is legal, which the backend re-checks. */
export function ModeControl(props: {
  mode: "chat" | "coding";
  onModeChange: (mode: "chat" | "coding") => void;
  projectId: string | undefined;
  onProjectChange: (id: string | undefined) => void;
}): JSX.Element {
  const projects = useProjects();

  /** Only projects a worktree can actually be cut from. A directory that isn't a
   *  repository yet is offered on the Projects screen with a CREATE A REPOSITORY
   *  step, which is an operator decision and not something to slip into a send. */
  const codeable = createMemo(() =>
    (projects.latest?.projects ?? []).filter(
      (p) => !p.archived && p.repo.exists && p.repo.isGitRepo,
    ),
  );

  const groups = createMemo(() => [
    {
      label: "PROJECTS",
      options: codeable().map((p) => ({ value: p.id, label: p.name })),
    },
  ]);

  const uncommitted = createMemo(() => {
    const chosen = codeable().find((p) => p.id === props.projectId);
    return chosen?.repo.uncommittedChanges ?? 0;
  });

  return (
    <div class="flex flex-wrap items-center gap-2">
      <Select
        value={props.mode}
        onChange={(v) => props.onModeChange(v === "coding" ? "coding" : "chat")}
        options={[
          { value: "chat", label: "CHAT" },
          { value: "coding", label: "CODING" },
        ]}
        aria-label="Conversation mode"
      />
      <Show when={props.mode === "coding"}>
        <Combobox
          groups={groups()}
          value={props.projectId ?? ""}
          onChange={(v) => props.onProjectChange(v || undefined)}
          leading="library"
          placeholder="PICK A PROJECT"
          searchPlaceholder="Search projects…"
          emptyHint="NO GIT PROJECTS — ADD ONE UNDER PROJECTS"
          aria-label="Project"
        />
        {/* The one thing that will surprise someone: a worktree branches from the
            project's base ref, so uncommitted work in the operator's own checkout
            is invisible to the agent. Said here rather than discovered halfway
            through a session. */}
        <Show when={props.projectId && uncommitted() > 0}>
          <Text variant="micro" tone="dim">
            {uncommitted()} UNCOMMITTED CHANGE
            {uncommitted() === 1 ? "" : "S"} WON'T BE VISIBLE
          </Text>
        </Show>
      </Show>
    </div>
  );
}
