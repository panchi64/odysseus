import { createSignal, Show, type JSX } from "solid-js";
import { SkillsDirectoryScreen } from "../screens/SkillsDirectoryScreen";
import { SkillEditorScreen } from "../screens/SkillEditorScreen";

/**
 * Skills as one settings section, two levels deep: the directory, and the editor
 * for whichever skill is open.
 *
 * The two used to be `/skills` and `/skills/{id}`, and the second level was the
 * router's job. Inside the dialog there is no route to carry it, so the open id
 * lives here — the one piece of state neither screen should own, since the
 * directory must not know an editor exists and the editor must not know what it
 * came from.
 *
 * The open id is deliberately **not** in the URL. `?settings=agent` addresses a
 * category, which is the unit an operator links to; a specific skill's editor is
 * a place you get to, not one you send someone.
 */
export function SkillsSection(): JSX.Element {
  const [openId, setOpenId] = createSignal<string | null>(null);
  return (
    <Show
      when={openId()}
      keyed
      fallback={<SkillsDirectoryScreen onOpen={setOpenId} />}
    >
      {(id) => <SkillEditorScreen id={id} onBack={() => setOpenId(null)} />}
    </Show>
  );
}
