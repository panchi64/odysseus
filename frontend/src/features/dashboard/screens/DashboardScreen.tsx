import { For, Show, createMemo, type JSX } from "solid-js";
import { useNavigate } from "@solidjs/router";
import {
  Composer,
  EmptyState,
  ListRow,
  PageHeader,
  Panel,
  Resource,
  StatusFlag,
  Text,
  Tooltip,
  type Status,
} from "~/ui";
import { overviewBand, useActiveRuns, useOverview } from "../data";
import type { ActiveRun, CapabilityHealth } from "../model";
import { RecentThreadCard } from "../components/RecentThreadCard";
import { SystemStrip } from "../components/SystemStrip";
// The overview is a launchpad INTO chat, so it reads the chat feature's data
// seam directly (one source of truth for threads and entry intents). The model
// selection is global app state — the picker itself is the shared `ModelPicker`,
// so this screen reads the selection but never renders its own control for it.
import {
  entrySessionId,
  openConversation,
  startConversation,
  useChatSessions,
} from "~/features/chat/data";
import {
  effectiveContextWindow,
  effectiveSelection,
  selectedModelLabel,
} from "~/lib/stores/models";
import { ModelPicker } from "~/app/ModelPicker";
import { createComposerAttachments } from "~/features/uploads/data";

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

/** Status → chip tone for an in-flight run. A parked run awaiting the operator's
 *  decision gets the warn accent — the others read as plain ambient activity. */
const RUN_STATUS_TONE: Record<ActiveRun["status"], Status> = {
  running: "info",
  queued: "idle",
  awaiting_input: "warn",
};

/** Home overview as a launchpad: a centered composer to start work, recent
 *  threads to resume it, in-flight runs, and a subtle system strip. Every panel
 *  reflects real backend state — the composer/threads via the chat seam, the
 *  facts band + capability health via `/overview`, the in-flight list via `/runs`. */
export function DashboardScreen(): JSX.Element {
  const navigate = useNavigate();
  const { data: overview, refetch: refetchOverview } = useOverview();
  const { data: runs } = useActiveRuns();
  const sessions = useChatSessions();
  // Files attached on the launchpad ride into the conversation's first turn.
  const attachments = createComposerAttachments();

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
    if (s === "alert") return "System alert";
    if (s === "warn") return "System warning";
    return "All systems";
  };

  // The capabilities responsible for the current flag — the same severity policy
  // as `computeOverallStatus`: down capabilities raise an alert, degraded
  // *critical* ones a warning. Their details become the flag's hover tooltip so
  // the operator sees *what* is wrong without leaving the launchpad.
  const alertReason = (): string | null => {
    const o = overview();
    if (!o) return null;
    const s = overallStatus();
    const triggering =
      s === "alert"
        ? o.capabilities.filter((c) => c.status === "alert")
        : s === "warn"
          ? o.capabilities.filter((c) => c.critical && c.status === "warn")
          : [];
    if (!triggering.length) return null;
    return triggering.map((c) => `${c.label}: ${c.detail}`).join(" · ");
  };

  const handleStart = (text: string, attachmentIds: string[]) => {
    startConversation(text, effectiveSelection(), attachmentIds);
    navigate("/chat");
  };
  const openThread = (id: string) => {
    openConversation(id);
    navigate("/chat");
  };

  return (
    <div class="flex min-h-full flex-col gap-6">
      <PageHeader
        title="Odysseus"
        subtitle="Your private, self-hosted AI workspace — chat, research, memory, and more."
        assetId="ODY-HUD-00.1 EDITION 02"
        actions={
          <Show
            when={alertReason()}
            fallback={
              <StatusFlag status={overallStatus()} dot>
                {overallLabel()}
              </StatusFlag>
            }
          >
            {(reason) => (
              <Tooltip label={reason()} side="left">
                <StatusFlag status={overallStatus()} dot>
                  {overallLabel()}
                </StatusFlag>
              </Tooltip>
            )}
          </Show>
        }
      />

      {/* Composer — the focal point, vertically centered in the free space. It
          is the only card on this screen that lights its accent on focus, which
          is what makes "start typing" the obvious move on arrival (§6.2). */}
      <div class="flex min-h-0 flex-1 items-center justify-center py-8">
        <div class="w-full max-w-3xl">
          <Composer
            size="lg"
            title="New conversation"
            autofocus
            storageKey="home-new"
            placeholder="Ask anything, request a summary, or describe a task…"
            onSend={handleStart}
            attachments={attachments}
            // Same slot, same component as the docked composer in a room: the
            // launchpad's picker was a second inline copy of the shared one, and two
            // copies of a control bound to one backend value is how they drift.
            trailing={<ModelPicker />}
          />
        </div>
      </div>

      {/* Bottom-aligned: recent threads + in-flight, then the system strip. */}
      <div class="flex flex-col gap-4">
        <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* Recent threads — the launchpad's navigation; default brightness. */}
          <Panel label="Recent threads" bare class="lg:col-span-2">
            <Show
              when={recent().length}
              fallback={
                <EmptyState
                  icon="terminal"
                  message="No conversations yet"
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
          <Panel label="In flight" bare class="lg:col-span-1">
            <Resource
              data={runs}
              emptyMessage="No active runs"
              isEmpty={(r) => r.length === 0}
            >
              {(list) => (
                <For each={list()}>
                  {(run) => {
                    // A run with no linked conversation (e.g. a bare research run)
                    // renders as a plain row — nothing to navigate to.
                    const clickable = () => !!run.conversationId;
                    return (
                      <ListRow
                        label={
                          <span class="flex min-w-0 items-center gap-2">
                            <Text variant="label" tone="dim">
                              {run.kind}
                            </Text>
                            <Text variant="micro" tone="dim" class="truncate">
                              {run.label}
                            </Text>
                          </span>
                        }
                        onClick={
                          clickable()
                            ? () => openThread(run.conversationId!)
                            : undefined
                        }
                        right={
                          <StatusFlag status={RUN_STATUS_TONE[run.status]}>
                            {run.detail}
                          </StatusFlag>
                        }
                      />
                    );
                  }}
                </For>
              )}
            </Resource>
          </Panel>
        </div>

        {/* System strip — most subtle; compact, marquees only if it overflows. */}
        <Resource
          data={overview}
          onRetry={refetchOverview}
          errorMessage="Telemetry unavailable"
        >
          {(o) => (
            <SystemStrip
              band={overviewBand(
                o(),
                selectedModelLabel(),
                effectiveContextWindow(),
              )}
              capabilities={o().capabilities}
            />
          )}
        </Resource>
      </div>
    </div>
  );
}
