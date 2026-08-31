import { For, Show, createMemo, createSignal, type JSX } from "solid-js";
import { SESSION_MODES } from "~/lib/modes";
import { Button, Icon, Text, Tooltip, cx, toast } from "~/ui";
import { usePathPicker } from "~/lib/hostPicker";
import { ensureProjectForPath, useProjects } from "~/lib/stores/projects";
import { mainChat } from "../data";

/**
 * **Which kind of work you are looking at** — the rail's first control, above the
 * threads it arranges.
 *
 * It used to be a dropdown in the composer, shown only while a thread was still
 * unsaved, because the mode was a property of the message being sent. It is not:
 * it is a property of the *thread*, and therefore of the list of threads. Here it
 * does one thing that reads as three — it files what the rail shows, decides what
 * the next new thread will be, and repaints the signature accent through
 * `data-mode` — because those are the same fact stated at three ranges.
 *
 * The mode of a thread already saved is still immutable and still the backend's:
 * a code thread owns a git branch, and re-pointing it would strand that branch.
 * Opening one moves this switch to match it rather than the other way round.
 */
export function SessionModeSwitch(): JSX.Element {
  const { mode, setMode, currentId } = mainChat();

  return (
    <div class="flex flex-col gap-1 px-2 pb-1">
      <div
        role="radiogroup"
        aria-label="Session mode"
        class="flex items-center gap-1 rounded-ctl bg-sunken p-0.5"
      >
        <For each={SESSION_MODES}>
          {(spec) => (
            <Tooltip
              delay={600}
              side="bottom"
              label={spec.description}
              class="min-w-0 flex-1"
            >
              <button
                type="button"
                role="radio"
                aria-checked={mode() === spec.id}
                onClick={() => setMode(spec.id)}
                class={cx(
                  "flex w-full items-center justify-center gap-1.5 rounded-ctl px-2 py-1.5 transition-colors hover:bg-raised",
                  // Selection is a raised fill on a smoothed corner, the same
                  // way the rail marks the page you are on — not a coloured pill,
                  // which would spend the signature accent on the control that
                  // *chooses* the signature accent.
                  mode() === spec.id && "bg-raised",
                )}
              >
                <Icon
                  name={spec.icon}
                  size={14}
                  class={mode() === spec.id ? "text-bright" : "text-dim"}
                />
                <Text
                  variant="label"
                  tone={mode() === spec.id ? "bright" : "dim"}
                >
                  {spec.label}
                </Text>
              </button>
            </Tooltip>
          )}
        </For>
      </div>

      {/* The workspace line belongs to Code alone, and only while a thread is
          still being staged: an existing code thread shows its branch in the
          status strip, and offering to re-point it here would be offering
          something the backend refuses. */}
      <Show when={mode() === "code" && currentId() === null}>
        <CodeWorkspaceLine />
      </Show>
    </div>
  );
}

/** Which directory the next code thread will work in — and the way to pick one.
 *
 *  Any directory does. Projects are still the storage and the git machinery, but
 *  they are no longer paperwork the operator files before they can start: the
 *  native chooser hands back a host path, and the backend files it on first use.
 *  A previously chosen directory stays staged, so the common case is not choosing
 *  anything at all. */
function CodeWorkspaceLine(): JSX.Element {
  const { codeProjectId, setCodeProjectId } = mainChat();
  const projects = useProjects();
  const picker = usePathPicker();
  const [choosing, setChoosing] = createSignal(false);

  const staged = createMemo(() =>
    (projects.latest?.projects ?? []).find((p) => p.id === codeProjectId()),
  );

  const choose = async () => {
    const pick = picker();
    if (!pick) {
      // No native chooser on this host. The Projects screen still takes a typed
      // path, so say where to go rather than leaving a dead button.
      toast.error(
        "No folder chooser on this host — add the directory under projects",
      );
      return;
    }
    setChoosing(true);
    try {
      const path = await pick({
        mode: "directory",
        title: "Choose a directory",
      });
      if (!path) return;
      const project = await ensureProjectForPath(path);
      setCodeProjectId(project.id);
      // Said once, here, rather than discovered halfway through a session: a
      // worktree is cut from the project's base ref, so work the operator has not
      // committed in their own checkout is invisible to the agent.
      if (!project.repo.isGitRepo)
        toast.error(
          `${project.name} isn't a git repository yet — create one under projects first`,
        );
      else if ((project.repo.uncommittedChanges ?? 0) > 0)
        toast.info(
          `${project.repo.uncommittedChanges} uncommitted change${
            project.repo.uncommittedChanges === 1 ? "" : "s"
          } in ${project.name} won't be visible to the agent`,
        );
    } catch (err) {
      toast.error(
        (err as { detail?: string })?.detail ?? "Couldn't open that directory",
      );
    } finally {
      setChoosing(false);
    }
  };

  return (
    <div class="flex items-center gap-2 pl-1">
      <Show
        when={staged()}
        fallback={
          <Button
            variant="ghost"
            size="sm"
            leading="library"
            disabled={choosing()}
            onClick={() => void choose()}
          >
            Choose a directory
          </Button>
        }
      >
        {(project) => (
          <>
            <Icon name="library" size={14} class="shrink-0 text-dim" />
            <Text variant="micro" tone="dim" class="min-w-0 flex-1 truncate">
              {project().name}
            </Text>
            <Button
              variant="ghost"
              size="sm"
              disabled={choosing()}
              onClick={() => void choose()}
            >
              Change
            </Button>
          </>
        )}
      </Show>
    </div>
  );
}
