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
import { useServices, useSystemBand, useTasks } from "../data";
import type { ServiceHealth } from "../mocks";
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

/** Derives the worst-case status from the service list for the ALL SYSTEMS flag. */
function computeOverallStatus(svcs: ServiceHealth[]): Status {
  if (svcs.some((s) => s.status === "alert")) return "alert";
  if (svcs.some((s) => s.status === "warn")) return "warn";
  return "nominal";
}

const RECENT_LIMIT = 6;

/** Home overview as a launchpad: a centered composer to start work, recent
 *  threads to resume it, in-flight tasks, and a subtle system strip. */
export function DashboardScreen(): JSX.Element {
  const navigate = useNavigate();
  const { data: systemBand, refetch: refetchBand } = useSystemBand();
  const { data: services } = useServices();
  const { data: tasks } = useTasks();
  const sessions = useChatSessions();

  // The resume target: the newest still-warm thread (or none).
  const entryId = createMemo(() => {
    const list = sessions();
    return list ? entrySessionId(list) : null;
  });
  const recent = createMemo(() => sessions()?.slice(0, RECENT_LIMIT) ?? []);

  const overallStatus = (): Status => {
    const svcs = services();
    return svcs ? computeOverallStatus(svcs) : "nominal";
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

          {/* In flight — most subtle: dim unless a task has failed. */}
          <Panel label="IN FLIGHT" flush class="lg:col-span-1">
            <Resource
              data={tasks}
              emptyMessage="NO ACTIVE TASKS"
              isEmpty={(t) => t.length === 0}
            >
              {(list) => (
                <For each={list()}>
                  {(task) => (
                    <div class="flex items-center justify-between gap-2 border-b border-line px-3 py-2 last:border-0">
                      <span class="flex min-w-0 items-center gap-2">
                        <Text variant="label" tone="dim">
                          {task.kind}
                        </Text>
                        <Text variant="micro" tone="dim" class="truncate">
                          {task.label}
                        </Text>
                      </span>
                      <Text
                        variant="micro"
                        tone={task.status === "failed" ? "alert" : "dim"}
                        class="shrink-0"
                      >
                        {task.status === "failed" ? "FAILED" : task.detail}
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
          data={systemBand}
          onRetry={refetchBand}
          errorMessage="TELEMETRY UNAVAILABLE"
        >
          {(band) => (
            <Show when={services()}>
              <SystemStrip band={band()} services={services()!} />
            </Show>
          )}
        </Resource>
      </div>
    </div>
  );
}
