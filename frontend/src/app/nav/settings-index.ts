/**
 * The settings registry — what the palette can change without going anywhere.
 *
 * Every entry is a **pointer**, not a home. `read` reads whatever the feature's
 * existing `data.ts` (or a theme/notification helper) already exposes, and
 * `write` calls that seam's own action. This module opens no new API surface,
 * holds no authoritative value, and decides nothing: the backend re-validates
 * every write and remains the authority (`min`/`max` here only shape the inline
 * field's immediate feedback).
 *
 * Two of the five groups are **dynamic** — the agent's tool catalog and the
 * endpoint catalog are the backend's to enumerate, never the frontend's, so
 * those rows are derived from the live resources rather than declared.
 *
 * Everything is built inside `useSettingsIndex`, which the palette calls from
 * *inside* its `Modal`. `Modal` renders its children only while open, so the
 * resources behind these rows are created when the palette opens and torn down
 * when it closes — the app pays nothing at boot for a surface used occasionally,
 * and each visit reads fresh.
 *
 * The pure derivations over these entries live in `./settings-search`.
 */

import { createMemo, createSignal, type Accessor } from "solid-js";
import {
  saveChatSettings,
  setAgentToolEnabled,
  setEndpointEnabled,
  setOfflineAutoDetect,
  setOfflineManual,
  refreshOfflineState,
  useAgentTools,
  useChatSettings,
  useEndpoints,
  useOfflineState,
} from "~/features/settings/data";
import type { ChatSettings } from "~/features/settings/model";
import {
  AUTO_CLEAR_OPTIONS,
  useNotifications,
} from "~/lib/stores/notifications";
import { preference, setTheme, THEME_CYCLE } from "~/ui";
import type { ThemePreference } from "~/ui";
import type { SettingChoice, SettingEntry } from "./types";

/** Group headings, in the order the directory lists them. Backend-owned
 *  behaviour first (it's what an operator comes here to change), the two
 *  catalogs next, then the client-side look-and-feel. */
const CHAT = "CHAT";
const OFFLINE = "OFFLINE";
const AGENT_TOOLS = "AGENT TOOLS";
const ENDPOINTS = "ENDPOINTS";
const APPEARANCE = "APPEARANCE";
const NOTIFICATIONS = "NOTIFICATIONS";

/** The theme preference spoken as options. Built from `THEME_CYCLE` so the
 *  palette can never offer a mode the toggle doesn't cycle through. */
const THEME_OPTIONS: readonly SettingChoice[] = THEME_CYCLE.map((value) => ({
  value,
  label: value.toUpperCase(),
}));

/**
 * The live settings index. Reactive: each `read` tracks its own seam, so a row
 * actioned in place re-renders with the new value and the palette stays open.
 */
export function useSettingsIndex(): Accessor<SettingEntry[]> {
  /* ── Chat (backend) ──────────────────────────────────────────────────────
     `useChatSettings` is a plain `createResource` with no refetch source, so a
     save doesn't feed back into it. `saveChatSettings` returns the full stored
     settings, so the response *is* the fresh read — parked here and preferred
     over the resource. Scoped to this call (not module-level) so it dies with
     the palette and can never mask a later fetch with a stale value. */
  const chatResource = useChatSettings();
  const [chatSaved, setChatSaved] = createSignal<ChatSettings | null>(null);
  // `.latest` rather than the resource call: the palette isn't inside a `Suspense`, and
  // reading a pending resource would suspend the overlay. `.latest` avoids *suspending*
  // but still re-throws a failed fetch, so it is guarded by `.error` — the same shape
  // `SkillsDirectoryScreen` use. A settings endpoint that is down must
  // cost the palette its rows, not blank the whole content region.
  const chat = (): ChatSettings | undefined =>
    chatSaved() ?? (chatResource.error ? undefined : chatResource.latest);
  const saveChat = async (patch: Partial<ChatSettings>): Promise<void> => {
    setChatSaved(await saveChatSettings(patch));
  };

  /* ── Offline (backend, live-polled signal) ───────────────────────────────
     The signal is only populated by a poll, and the Offline screen is what
     normally polls it. Seed it once on open so the rows show real state instead
     of a dash; the two setters reflect the PUT's own response afterwards. */
  const offline = useOfflineState();
  void refreshOfflineState();

  /* ── The two catalogs (backend-enumerated) ───────────────────────────────── */
  const tools = useAgentTools();
  const endpoints = useEndpoints();

  /* ── Client-side preferences ─────────────────────────────────────────────── */
  const notifications = useNotifications();

  const staticEntries = (): SettingEntry[] => [
    {
      id: "chat.auto-compact",
      label: "Auto-compact conversations",
      keywords: ["compaction", "fold", "summary", "context", "window"],
      group: CHAT,
      kind: "toggle",
      read: () => chat()?.autoCompactEnabled,
      write: (next) => saveChat({ autoCompactEnabled: next }),
    },
    {
      id: "chat.auto-compact-threshold",
      label: "Auto-compact trigger",
      keywords: ["compaction", "threshold", "percent", "context", "window"],
      group: CHAT,
      kind: "number",
      unit: "%",
      min: 1,
      max: 100,
      // Stored as a 0–1 fraction, thought about as a percentage — the same one
      // conversion Settings → CHAT does, and the only one either surface does.
      read: () => {
        const s = chat();
        return s === undefined
          ? undefined
          : Math.round(s.autoCompactThreshold * 100);
      },
      write: (next) => saveChat({ autoCompactThreshold: next / 100 }),
    },
    {
      id: "chat.context-warn",
      label: "Context gauge warning",
      keywords: ["context", "ring", "gauge", "amber", "threshold", "percent"],
      group: CHAT,
      kind: "number",
      unit: "%",
      min: 1,
      max: 99,
      read: () => {
        const s = chat();
        return s === undefined
          ? undefined
          : Math.round(s.contextWarnThreshold * 100);
      },
      write: (next) => saveChat({ contextWarnThreshold: next / 100 }),
    },
    {
      id: "chat.context-alert",
      label: "Context gauge alert",
      keywords: ["context", "ring", "gauge", "red", "threshold", "percent"],
      group: CHAT,
      kind: "number",
      unit: "%",
      min: 2,
      max: 100,
      read: () => {
        const s = chat();
        return s === undefined
          ? undefined
          : Math.round(s.contextAlertThreshold * 100);
      },
      write: (next) => saveChat({ contextAlertThreshold: next / 100 }),
    },
    {
      id: "chat.step-limit",
      label: "Step limit per turn",
      keywords: ["agent", "requests", "rounds", "budget", "runaway"],
      group: CHAT,
      kind: "number",
      min: 1,
      read: () => chat()?.agentRequestLimit,
      write: (next) => saveChat({ agentRequestLimit: next }),
    },
    {
      id: "chat.inactivity-timeout",
      label: "Inactivity timeout",
      keywords: ["watchdog", "stall", "silent", "seconds"],
      group: CHAT,
      kind: "number",
      unit: "s",
      min: 1,
      read: () => chat()?.inactivityTimeoutS,
      write: (next) => saveChat({ inactivityTimeoutS: next }),
    },
    {
      id: "offline.manual",
      label: "Force offline mode",
      keywords: ["network", "disconnect", "air gap", "web"],
      group: OFFLINE,
      kind: "toggle",
      read: () => offline()?.manualOffline,
      write: (next) => setOfflineManual(next),
    },
    {
      id: "offline.auto-detect",
      label: "Auto-detect connectivity",
      keywords: ["network", "monitor", "web"],
      group: OFFLINE,
      kind: "toggle",
      read: () => offline()?.autoDetect,
      write: (next) => setOfflineAutoDetect(next),
    },
    {
      id: "ui.theme",
      label: "Theme",
      keywords: ["phosphor", "paper", "dark", "light", "palette", "colour"],
      group: APPEARANCE,
      kind: "choice",
      options: THEME_OPTIONS,
      read: () => preference(),
      write: (next) => setTheme(next as ThemePreference),
    },
    {
      id: "ui.notification-auto-clear",
      label: "Notification auto-clear",
      keywords: ["bell", "dismiss", "timeout", "badge"],
      group: NOTIFICATIONS,
      kind: "choice",
      options: AUTO_CLEAR_OPTIONS,
      read: () => String(notifications.autoClearSeconds),
      write: (next) => notifications.setAutoClearSeconds(Number(next)),
    },
  ];

  /** One row per tool the backend reports. Its category and description ride
   *  along as keywords, so a tool is findable by what it does as well as by the
   *  namespaced name it's offered to the agent under. */
  const toolEntries = (): SettingEntry[] =>
    // `.error`-guarded like `chat` above: `.latest` re-throws a failed fetch.
    (tools.error ? [] : (tools.latest ?? [])).map((tool) => ({
      id: `tool.${tool.name}`,
      label: tool.name,
      keywords: ["tool", tool.category, tool.description],
      group: AGENT_TOOLS,
      kind: "toggle" as const,
      read: () => tool.enabled,
      write: (next: boolean) => setAgentToolEnabled(tool.name, next),
    }));

  /** One row per configured endpoint — the enable/disable flip only. Everything
   *  else about an endpoint (its key, its model, its chain position) is editing,
   *  not toggling, and belongs on the Models page. */
  const endpointEntries = (): SettingEntry[] =>
    (endpoints.error ? [] : (endpoints.latest ?? [])).map((endpoint) => ({
      id: `endpoint.${endpoint.id}`,
      label: endpoint.name,
      keywords: [
        "endpoint",
        "model",
        endpoint.provider,
        endpoint.model ?? "",
        endpoint.baseUrl,
      ],
      group: ENDPOINTS,
      kind: "toggle" as const,
      read: () => endpoint.enabled,
      write: (next: boolean) => setEndpointEnabled(endpoint.id, next),
    }));

  return createMemo(() => [
    ...staticEntries(),
    ...toolEntries(),
    ...endpointEntries(),
  ]);
}
