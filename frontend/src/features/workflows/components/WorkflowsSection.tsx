import { createSignal, Show, type JSX } from "solid-js";
import { WorkflowsDirectoryScreen } from "../screens/WorkflowsDirectoryScreen";
import { WorkflowEditorScreen } from "../screens/WorkflowEditorScreen";

/**
 * Workflows as one settings section, two levels deep: the directory, and the editor for
 * whichever workflow is open.
 *
 * The open id lives here — the one piece of state neither screen should own, since the
 * directory must not know an editor exists and the editor must not know what it came
 * from. It is deliberately **not** in the URL: `?settings=workflows` addresses a
 * category, which is the unit an operator links to; a specific template's editor is a
 * place you get to, not one you send someone. The same shape `SkillsSection` keeps, for
 * the same reasons.
 */
export function WorkflowsSection(): JSX.Element {
  const [openId, setOpenId] = createSignal<string | null>(null);
  return (
    <Show
      when={openId()}
      keyed
      fallback={<WorkflowsDirectoryScreen onOpen={setOpenId} />}
    >
      {(id) => <WorkflowEditorScreen id={id} onBack={() => setOpenId(null)} />}
    </Show>
  );
}
