import { createMemo, Show, type JSX } from "solid-js";
import { Select, Text, toast } from "~/ui";
import {
  activeProjectId,
  isUnscoped,
  setActiveProject,
  setUnscoped,
  useProjects,
} from "~/lib/stores/projects";
import { useSettingsRoute } from "~/app/settings-dialog";

/** Sentinels. Real project ids are hex, so neither can collide with one. */
const ALL = "__all__";
const NONE = "__none__";
const MANAGE = "__manage__";

/** The project scope, above the area switcher.
 *
 *  Deliberately a third, quieter tier rather than a rail slot: `railSlots` is
 *  path-matched (RECENTS only exists on /chat), and the scope has to be readable and
 *  changeable from every surface it affects — which is most of them.
 *
 *  It renders nothing until the operator has at least one project. A control that
 *  scopes nothing is just a row of vertical space explaining a feature they haven't
 *  used, and the app before projects is exactly the app with none. */
export function ProjectSwitcher(): JSX.Element {
  const projects = useProjects();
  const settings = useSettingsRoute();

  const options = createMemo(() => {
    const rows = (projects.latest?.projects ?? []).filter((p) => !p.archived);
    return [
      { value: NONE, label: "Unfiled only" },
      { value: ALL, label: "All projects" },
      ...rows.map((p) => ({ value: p.id, label: p.name.toUpperCase() })),
      { value: MANAGE, label: "Manage projects…" },
    ];
  });

  const value = (): string =>
    isUnscoped() ? ALL : (activeProjectId() ?? NONE);

  const onChange = (next: string): void => {
    if (next === MANAGE) {
      // Projects is a section of the AGENT category now, not a page. The `/projects`
      // route still forwards there, but going through it would push a navigation
      // the operator never asked for — this opens the dialog where they stand.
      settings.show("agent");
      return;
    }
    if (next === ALL) {
      setUnscoped(true);
      return;
    }
    setUnscoped(false);
    void setActiveProject(next === NONE ? null : next).catch((err: unknown) => {
      toast.error(
        err instanceof Error ? err.message : "Could not switch project",
      );
    });
  };

  return (
    <Show when={(projects.latest?.projects ?? []).length > 0}>
      <div class="px-3 py-2">
        <Text variant="label" tone="dim">
          Project
        </Text>
        <Select
          options={options()}
          value={value()}
          onChange={onChange}
          class="mt-1"
        />
      </div>
    </Show>
  );
}
