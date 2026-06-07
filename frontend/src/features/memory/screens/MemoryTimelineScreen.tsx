import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  Divider,
  EmptyState,
  Icon,
  InstrumentBand,
  ListRow,
  LoadingText,
  Menu,
  Modal,
  PageHeader,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Tabs,
  Text,
  type Status,
} from "~/ui";
import { relativeTime, num } from "~/lib/format";
import { useMemories, useDedupCandidates } from "../data";
import type { MemoryType } from "../model";

const typeStatus: Record<MemoryType, Status> = {
  user: "info",
  feedback: "nominal",
  project: "warn",
  reference: "idle",
};

const TYPE_TABS = [
  { value: "all", label: "ALL" },
  { value: "user", label: "USER" },
  { value: "feedback", label: "FEEDBACK" },
  { value: "project", label: "PROJECT" },
  { value: "reference", label: "REFERENCE" },
];

export function MemoryTimelineScreen(): JSX.Element {
  const memories = useMemories();
  const dedupCandidates = useDedupCandidates();
  const [typeFilter, setTypeFilter] = createSignal("all");
  const [dedupOpen, setDedupOpen] = createSignal(false);

  const filtered = () => {
    const all = memories() ?? [];
    const f = typeFilter();
    if (f === "all") return all;
    return all.filter((m) => m.type === f);
  };

  const pinned = () => (memories() ?? []).filter((m) => m.pinned).length;
  const byType = (t: MemoryType) =>
    (memories() ?? []).filter((m) => m.type === t).length;

  return (
    <Stack gap={6}>
      <PageHeader
        title="MEMORY"
        subtitle="Persistent facts, preferences, and context the system has learned."
        assetId="ODY-MEM-01.0"
        actions={
          <Row gap={2}>
            <Button
              variant="default"
              leading="search"
              onClick={() => setDedupOpen(true)}
            >
              DEDUP AUDIT
            </Button>
            <Button variant="primary" leading="plus">
              ADD MEMORY
            </Button>
          </Row>
        }
      />

      <InstrumentBand
        items={[
          { label: "TOTAL", value: String((memories() ?? []).length) },
          { label: "PINNED", value: String(pinned()), tone: "nominal" },
          { label: "USER", value: String(byType("user")), tone: "info" },
          { label: "PROJECT", value: String(byType("project")), tone: "warn" },
          {
            label: "REFERENCE",
            value: String(byType("reference")),
            tone: "dim",
          },
          {
            label: "FEEDBACK",
            value: String(byType("feedback")),
            tone: "nominal",
          },
        ]}
      />

      <Panel flush>
        <div class="border-b border-line">
          <Tabs
            items={TYPE_TABS}
            value={typeFilter()}
            onChange={setTypeFilter}
          />
        </div>

        <Suspense
          fallback={
            <div class="p-4">
              <LoadingText />
            </div>
          }
        >
          <Show
            when={filtered().length}
            fallback={
              <EmptyState
                icon="database"
                message="NO MEMORIES"
                hint="No memories match the current filter."
              />
            }
          >
            <For each={filtered()}>
              {(mem) => (
                <ListRow
                  label={mem.text}
                  leading={mem.pinned ? "lock" : "dot"}
                  right={
                    <span class="flex items-center gap-3 shrink-0">
                      <StatusFlag status={typeStatus[mem.type]}>
                        {mem.type.toUpperCase()}
                      </StatusFlag>
                      <Text variant="micro" tone="dim">
                        {relativeTime(mem.createdAt)}
                      </Text>
                      <Menu
                        trigger={
                          <span class="px-1 text-dim hover:text-bright">
                            <Text variant="micro">···</Text>
                          </span>
                        }
                        items={[
                          {
                            label: mem.pinned ? "UNPIN" : "PIN",
                            icon: "lock",
                            onSelect: () => {},
                          },
                          { label: "EDIT", icon: "edit", onSelect: () => {} },
                          {
                            label: "DELETE",
                            icon: "trash",
                            danger: true,
                            onSelect: () => {},
                          },
                        ]}
                      />
                    </span>
                  }
                />
              )}
            </For>
          </Show>
        </Suspense>
      </Panel>

      {/* Dedup Audit Modal */}
      <Modal
        open={dedupOpen()}
        onClose={() => setDedupOpen(false)}
        title="DEDUP AUDIT"
        class="max-w-2xl"
        footer={
          <Button variant="ghost" onClick={() => setDedupOpen(false)}>
            CLOSE
          </Button>
        }
      >
        <Suspense fallback={<LoadingText />}>
          <Show
            when={(dedupCandidates() ?? []).length}
            fallback={
              <EmptyState
                icon="check"
                message="NO DUPLICATES FOUND"
                hint="All memories appear distinct."
              />
            }
          >
            <Stack gap={4}>
              <Text variant="body" tone="dim">
                {(dedupCandidates() ?? []).length} candidate pair(s) detected
                above similarity threshold.
              </Text>
              <For each={dedupCandidates() ?? []}>
                {(pair) => (
                  <div class="border border-line">
                    <div class="flex items-center justify-between border-b border-line bg-raised px-4 py-2">
                      <Text variant="label" tone="dim">
                        SIMILARITY
                      </Text>
                      <Text variant="readout" tone="warn">
                        {num(pair.similarity * 100, 0)}%
                      </Text>
                    </div>
                    <div class="p-4">
                      <Stack gap={3}>
                        <div class="border-l-2 border-info pl-3">
                          <Text variant="body">{pair.a.text}</Text>
                          <Text variant="micro" tone="dim">
                            {relativeTime(pair.a.createdAt)}
                          </Text>
                        </div>
                        <div class="flex items-center gap-2">
                          <Divider />
                          <Icon
                            name="compare"
                            size={12}
                            class="text-dim shrink-0"
                          />
                          <Divider />
                        </div>
                        <div class="border-l-2 border-warn pl-3">
                          <Text variant="body">{pair.b.text}</Text>
                          <Text variant="micro" tone="dim">
                            {relativeTime(pair.b.createdAt)}
                          </Text>
                        </div>
                        <Row gap={2}>
                          <Button variant="danger" size="sm" leading="trash">
                            MERGE
                          </Button>
                          <Button variant="ghost" size="sm">
                            KEEP BOTH
                          </Button>
                        </Row>
                      </Stack>
                    </div>
                  </div>
                )}
              </For>
            </Stack>
          </Show>
        </Suspense>
      </Modal>
    </Stack>
  );
}
