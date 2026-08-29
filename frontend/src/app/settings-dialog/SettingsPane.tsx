import { For, Show, type JSX } from "solid-js";
import { Stack } from "~/ui";
import {
  AgentToolsPanel,
  AppearanceSection,
  ChatSection,
  ModelsScreen,
  OfflineSection,
  SearchProvidersPanel,
} from "~/features/settings";
import { MemoryTimelineScreen } from "~/features/memory";
import { ProjectsScreen } from "~/features/projects";
import { SkillsSection } from "~/features/skills";
import { VaultScreen } from "~/features/vault";
import { ApiTokensScreen } from "~/features/tokens";
import { AccessTokensScreen } from "~/features/access-tokens";
import { IntegrationsScreen } from "~/features/integrations";
import { BackupScreen } from "~/features/backup";
import { HealthScreen } from "~/features/health";
import type { SettingsCategory } from "./categories";

/**
 * The one place a section id becomes a component. `categories.ts` says what
 * exists and in what order; this says what each entry renders, and nothing else
 * knows both — so adding a section is one line in each file, and forgetting the
 * line here is what the dev warning below catches. It is a warning rather than a
 * test because importing this map constructs every feature's resources at module
 * load, and the unit suite has no DOM to hold them.
 *
 * Every value here is a **thunk**, not an element. Solid evaluates JSX eagerly,
 * so a map of elements would construct all fourteen sections — and create every
 * resource behind them — the moment this module is read, which is exactly the
 * cost the dialog's mount-only-while-open gate exists to avoid.
 */
export const SECTION_RENDERERS: Record<string, () => JSX.Element> = {
  "general.appearance": () => <AppearanceSection />,
  "general.chat": () => <ChatSection />,
  "general.offline": () => <OfflineSection />,
  "agent.tools": () => <AgentToolsPanel />,
  "agent.search": () => <SearchProvidersPanel />,
  "agent.skills": () => <SkillsSection />,
  "agent.projects": () => <ProjectsScreen />,
  "memory.facts": () => <MemoryTimelineScreen />,
  "models.roles": () => <ModelsScreen />,
  "security.vault": () => <VaultScreen />,
  "security.service-keys": () => <ApiTokensScreen />,
  "security.access-tokens": () => <AccessTokensScreen />,
  "system.integrations": () => <IntegrationsScreen />,
  "system.backup": () => <BackupScreen />,
  "system.health": () => <HealthScreen />,
};

/**
 * The dialog's right column: the picked category's sections, stacked.
 *
 * Keyed on the category id, so switching category **remounts** the pane rather
 * than diffing one set of sections into another. That is deliberate: these
 * sections own resources and local form state, and a category you navigate away
 * from should let go of both — the same reasoning that puts the whole dialog
 * behind a mount gate, applied one level down.
 */
export function SettingsPane(props: {
  category: SettingsCategory;
}): JSX.Element {
  return (
    <Show keyed when={props.category}>
      {(category) => (
        <Stack gap={8}>
          <For each={category.sections}>
            {(id) => {
              const render = SECTION_RENDERERS[id];
              // A section listed in `categories.ts` with no renderer here is a
              // silently blank pane — the exact failure a build cannot see. Say
              // so in dev; in production, render nothing rather than throw.
              if (!render && import.meta.env.DEV)
                console.warn(
                  `[settings] no renderer for section "${id}" — see SettingsPane.tsx`,
                );
              return <Show when={render}>{render?.()}</Show>;
            }}
          </For>
        </Stack>
      )}
    </Show>
  );
}
