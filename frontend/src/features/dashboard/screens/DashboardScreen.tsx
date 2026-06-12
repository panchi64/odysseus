import { For, Show, createMemo, type JSX } from "solid-js";
import { useNavigate } from "@solidjs/router";
import {
  Combobox,
  Composer,
  EmptyState,
  PageHeader,
  Panel,
  Resource,
  StatusFlag,
  Text,
  type Status,
} from "~/ui";
import { overviewBand, useActiveRuns, useOverview } from "../data";
import type { CapabilityHealth } from "../model";
import { RecentThreadCard } from "../components/RecentThreadCard";
import { SystemStrip } from "../components/SystemStrip";
// The overview is a launchpad INTO chat, so it reads the chat feature's data
// seam directly (one source of truth for threads and entry intents). The model
// selection is global app state, shared with the top-bar picker.
import {
  entrySessionId,
  openConversation,
  startConversation,
  useChatSessions,
} from "~/features/chat/data";
import {
  effectiveSelection,
  effectiveValue,
  modelPickerGroups,
  selectModelByValue,
} from "~/lib/stores/models";

/** Overall status for the header flag. Any down capability is an alert; a
 *  degraded *critical* capability is a warning. Non-critical degradations
 *  (e.g. keyword-only recall) stay off the top-level flag but still show as
 *  dots in the strip — the backend's `critical` flag is the severity policy. */
function computeOverallStatus(caps: CapabilityHealth[]): Status {
  if (caps.some((c) => c.status === "alert")) return "alert";
  if (caps.some((c) => c.critical && c.status === "warn")) return "warn";
  return "nominal";
}

const RECENT_LIMIT = 6;

/** Home overview as a launchpad: a centered composer to start work, recent
 *  threads to resume it, in-flight runs, and a subtle system strip. Every panel
 *  reflects real backend state — the composer/threads via the chat seam, the
 *  facts band + capability health via `/overview`, the in-flight list via `/runs`. */
export function DashboardScreen(): JSX.Element {
  const navigate = useNavigate();
  const { data: overview, refetch: refetchOverview } = useOverview();
  const { data: runs } = useActiveRuns();
  const sessions = useChatSessions();

  // The resume target: the newest still-warm thread (or none).
  const entryId = createMemo(() => {
    const list = sessions();
    return list ? entrySessionId(list) : null;
  });
  const recent = createMemo(() => sessions()?.slice(0, RECENT_LIMIT) ?? []);

  const overallStatus = (): Status => {
    const o = overview();
    return o ? computeOverallStatus(o.capabilities) : "nominal";
  };
  const overallLabel = (): string => {
    const s = overallStatus();
    if (s === "alert") return "SYSTEM ALERT";
    if (s === "warn") return "SYSTEM WARNING";
    return "ALL SYSTEMS";
  };

  const handleStart = (text: string) => {
    startConversation(text, effectiveSelection());
    navigate("/chat");
  };
  const openThread = (id: string) => {
    openConversation(id);
    navigate("/chat");
  };

  return (
    <div class="flex min-h-full flex-col gap-6">
      <PageHeader
        title="ODYSSEUS"
        subtitle="Your private, self-hosted AI workspace — chat, research, memory, and more."
        assetId="ODY-HUD-00.1 EDITION 02"
        actions={
          <StatusFlag status={overallStatus()} dot>
            {overallLabel()}
          </StatusFlag>
        }
      />

      {/* Composer — the focal point, vertically centered in the free space. */}
      <div class="flex min-h-0 flex-1 items-center justify-center py-4">
        <div class="w-full max-w-2xl">
          <Composer
            size="lg"
            title="NEW CONVERSATION"
            autofocus
            storageKey="home-new"
            placeholder="Ask anything, request a summary, or describe a task…"
            onSend={handleStart}
            controls={
              <Combobox
                groups={modelPickerGroups()}
                value={effectiveValue()}
                onChange={selectModelByValue}
                leading="cpu"
                placeholder="NO MODEL"
                searchPlaceholder="Search models…"
                emptyHint="NO MODELS — ADD AN ENDPOINT IN SETTINGS"
                aria-label="Model"
              />
            }
          />
        </div>
      </div>

      {/* Bottom-aligned: recent threads + in-flight, then the system strip. */}
      <div class="flex flex-col gap-4">
        <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* Recent threads — the launchpad's navigation; default brightness. */}
          <Panel label="RECENT THREADS" class="lg:col-span-2">
            <Show
              when={recent().length}
              fallback={
                <EmptyState
                  icon="terminal"
                  message="NO CONVERSATIONS YET"
                  hint="Start one above to see it here."
                />
              }
            >
              <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <For each={recent()}>
                  {(s) => (
                    <RecentThreadCard
                      title={s.title}
                      preview={s.preview}
                      model={s.model}
                      updatedAt={s.updatedAt}
                      warm={s.id === entryId()}
                      onOpen={() => openThread(s.id)}
                    />
                  )}
                </For>
              </div>
            </Show>
          </Panel>

          {/* In flight — most subtle: real runs not yet terminal. */}
          <Panel label="IN FLIGHT" flush class="lg:col-span-1">
            <Resource
              data={runs}
              emptyMessage="NO ACTIVE RUNS"
              isEmpty={(r) => r.length === 0}
            >
              {(list) => (
                <For each={list()}>
                  {(run) => (
                    <div class="flex items-center justify-between gap-2 border-b border-line px-3 py-2 last:border-0">
                      <span class="flex min-w-0 items-center gap-2">
                        <Text variant="label" tone="dim">
                          {run.kind}
                        </Text>
                        <Text variant="micro" tone="dim" class="truncate">
                          {run.label}
                        </Text>
                      </span>
                      <Text
                        variant="micro"
                        tone={run.status === "awaiting_input" ? "warn" : "dim"}
                        class="shrink-0"
                      >
                        {run.detail}
                      </Text>
                    </div>
                  )}
                </For>
              )}
            </Resource>
          </Panel>
        </div>

        {/* System strip — most subtle; compact, marquees only if it overflows. */}
        <Resource
          data={overview}
          onRetry={refetchOverview}
          errorMessage="TELEMETRY UNAVAILABLE"
        >
          {(o) => (
            <SystemStrip
              band={overviewBand(o())}
              capabilities={o().capabilities}
            />
          )}
        </Resource>
      </div>
    </div>
  );
}
