import {
  createMemo,
  createSignal,
  For,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import {
  Button,
  Checkbox,
  Divider,
  EmptyState,
  InstrumentBand,
  ListRow,
  ListToolbar,
  LoadingText,
  Menu,
  Modal,
  PageHeader,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
  Textarea,
  Input,
  confirm,
  toast,
} from "~/ui";
import { createListView } from "~/lib/list";
import { num, relativeTime } from "~/lib/format";
import {
  addMemory,
  auditDuplicates,
  deleteMemory,
  recall,
  updateMemory,
  useMemories,
} from "../data";
import type { DuplicateGroup, Memory, RecallHit } from "../model";

export function MemoryTimelineScreen(): JSX.Element {
  const memories = useMemories();

  const view = createListView<Memory>({
    source: () => memories() ?? [],
    search: (m) => m.content,
    sorts: {
      recent: {
        label: "NEWEST",
        compare: (a, b) => a.createdAt.localeCompare(b.createdAt),
      },
    },
    initialSort: "recent",
    initialDir: "desc",
  });

  const counts = createMemo(() => {
    const all = memories() ?? [];
    let pinned = 0;
    let embedded = 0;
    for (const m of all) {
      if (m.pinned) pinned++;
      if (m.hasEmbedding) embedded++;
    }
    return { total: all.length, pinned, embedded };
  });

  /* ── Add / edit ─────────────────────────────────────────────────────────── */
  const [editing, setEditing] = createSignal<Memory | null>(null);
  const [composeOpen, setComposeOpen] = createSignal(false);
  const [draft, setDraft] = createSignal("");
  const [draftPinned, setDraftPinned] = createSignal(false);
  const [saving, setSaving] = createSignal(false);

  const openAdd = () => {
    setEditing(null);
    setDraft("");
    setDraftPinned(false);
    setComposeOpen(true);
  };
  const openEdit = (m: Memory) => {
    setEditing(m);
    setDraft(m.content);
    setDraftPinned(m.pinned);
    setComposeOpen(true);
  };
  const saveDraft = async () => {
    const content = draft().trim();
    if (!content || saving()) return;
    setSaving(true);
    try {
      const target = editing();
      if (target) {
        await updateMemory(target.id, { content, pinned: draftPinned() });
        toast.success("Memory updated");
      } else {
        await addMemory(content, draftPinned());
        toast.success("Memory added");
      }
      setComposeOpen(false);
    } catch {
      toast.error("Unable to save the memory.");
    } finally {
      setSaving(false);
    }
  };

  const handlePin = async (m: Memory) => {
    try {
      await updateMemory(m.id, { pinned: !m.pinned });
      toast.success(m.pinned ? "Memory unpinned" : "Memory pinned");
    } catch {
      toast.error("Unable to update the memory.");
    }
  };

  const handleDelete = async (m: Memory) => {
    const preview =
      m.content.length > 80 ? m.content.slice(0, 80) + "…" : m.content;
    if (
      !(await confirm({
        title: "Delete memory?",
        detail: `"${preview}" — this cannot be undone.`,
        confirmLabel: "DELETE",
        tone: "alert",
      }))
    )
      return;
    try {
      await deleteMemory(m.id);
      toast.success("Memory deleted");
    } catch {
      toast.error("Unable to delete the memory.");
    }
  };

  /* ── Recall ─────────────────────────────────────────────────────────────── */
  const [recallOpen, setRecallOpen] = createSignal(false);
  const [recallQuery, setRecallQuery] = createSignal("");
  const [recallHits, setRecallHits] = createSignal<RecallHit[] | null>(null);
  const [recalling, setRecalling] = createSignal(false);
  const runRecall = async () => {
    const q = recallQuery().trim();
    if (!q || recalling()) return;
    setRecalling(true);
    try {
      setRecallHits(await recall(q, 8));
    } catch {
      toast.error("Recall failed.");
    } finally {
      setRecalling(false);
    }
  };

  /* ── Dedup audit ────────────────────────────────────────────────────────── */
  const [dedupOpen, setDedupOpen] = createSignal(false);
  const [groups, setGroups] = createSignal<DuplicateGroup[] | null>(null);
  const [auditing, setAuditing] = createSignal(false);
  const openDedup = async () => {
    setDedupOpen(true);
    setAuditing(true);
    try {
      setGroups(await auditDuplicates(memories() ?? []));
    } catch {
      toast.error("Audit failed.");
      setGroups([]);
    } finally {
      setAuditing(false);
    }
  };
  const deleteFromGroup = async (m: Memory) => {
    try {
      await deleteMemory(m.id);
      setGroups((gs) =>
        (gs ?? [])
          .map((g) => ({
            ...g,
            memories: g.memories.filter((x) => x.id !== m.id),
          }))
          .filter((g) => g.memories.length > 1),
      );
      toast.success("Memory deleted");
    } catch {
      toast.error("Unable to delete the memory.");
    }
  };

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
              onClick={() => {
                setRecallHits(null);
                setRecallQuery("");
                setRecallOpen(true);
              }}
            >
              RECALL
            </Button>
            <Button variant="default" leading="copy" onClick={openDedup}>
              DEDUP AUDIT
            </Button>
            <Button variant="primary" leading="plus" onClick={openAdd}>
              ADD MEMORY
            </Button>
          </Row>
        }
      />

      <InstrumentBand
        items={[
          { label: "TOTAL", value: String(counts().total) },
          { label: "PINNED", value: String(counts().pinned), tone: "nominal" },
          {
            label: "EMBEDDED",
            value: String(counts().embedded),
            tone: "info",
          },
        ]}
      />

      <Panel flush>
        <div class="border-b border-line p-3">
          <ListToolbar
            query={view.query()}
            onQueryChange={view.setQuery}
            placeholder="Filter memories…"
            sortKey={view.sortKey()}
            sortOptions={view.sortOptions}
            onSortChange={view.setSort}
            dir={view.dir()}
            onToggleDir={view.toggleDir}
            count={view.count()}
            total={view.total()}
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
            when={view.items().length}
            fallback={
              <EmptyState
                icon="database"
                message="NO MEMORIES"
                hint={
                  view.isFiltered()
                    ? "No memories match your filter."
                    : "Nothing stored yet. Add a memory or let the assistant learn one."
                }
              />
            }
          >
            <For each={view.items()}>
              {(mem) => (
                <ListRow
                  label={mem.content}
                  leading={mem.pinned ? "lock" : "dot"}
                  right={
                    <span class="flex shrink-0 items-center gap-3">
                      <Show when={mem.hasEmbedding}>
                        <StatusFlag status="info">EMB</StatusFlag>
                      </Show>
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
                            onSelect: () => handlePin(mem),
                          },
                          {
                            label: "EDIT",
                            icon: "edit",
                            onSelect: () => openEdit(mem),
                          },
                          {
                            label: "DELETE",
                            icon: "trash",
                            danger: true,
                            onSelect: () => handleDelete(mem),
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

      {/* Add / edit memory */}
      <Modal
        open={composeOpen()}
        onClose={() => setComposeOpen(false)}
        title={editing() ? "EDIT MEMORY" : "ADD MEMORY"}
      >
        <Stack gap={3}>
          <Textarea
            label="CONTENT"
            value={draft()}
            onInput={(e) => setDraft(e.currentTarget.value)}
            placeholder="A fact, preference, or piece of context to remember…"
            rows={5}
          />
          <Checkbox
            label="PINNED — always included in recall"
            checked={draftPinned()}
            onChange={setDraftPinned}
          />
          <div class="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setComposeOpen(false)}>
              CANCEL
            </Button>
            <Button
              variant="primary"
              disabled={!draft().trim() || saving()}
              onClick={saveDraft}
            >
              {saving() ? "SAVING…" : "SAVE"}
            </Button>
          </div>
        </Stack>
      </Modal>

      {/* Recall */}
      <Modal
        open={recallOpen()}
        onClose={() => setRecallOpen(false)}
        title="RECALL"
        class="max-w-2xl"
      >
        <Stack gap={4}>
          <Row gap={2} align="end">
            <div class="flex-1">
              <Input
                label="QUERY"
                value={recallQuery()}
                onInput={(e) => setRecallQuery(e.currentTarget.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void runRecall();
                }}
                placeholder="What should the assistant recall?"
              />
            </div>
            <Button
              variant="primary"
              disabled={!recallQuery().trim() || recalling()}
              onClick={runRecall}
            >
              {recalling() ? "RECALLING…" : "RECALL"}
            </Button>
          </Row>
          <Show when={recallHits()}>
            <Show
              when={recallHits()!.length}
              fallback={
                <EmptyState
                  icon="search"
                  message="NO HITS"
                  hint="Nothing recalled for that query."
                />
              }
            >
              <Stack gap={2}>
                <For each={recallHits()!}>
                  {(hit) => (
                    <div class="border border-line p-3">
                      <Row justify="between" align="center">
                        <StatusFlag status="info">
                          {hit.matchedBy.toUpperCase()}
                        </StatusFlag>
                        <Text variant="micro" tone="dim">
                          SCORE {num(hit.score, 3)}
                        </Text>
                      </Row>
                      <Text variant="body" class="mt-2">
                        {hit.content}
                      </Text>
                    </div>
                  )}
                </For>
              </Stack>
            </Show>
          </Show>
        </Stack>
      </Modal>

      {/* Dedup audit */}
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
        <Show
          when={!auditing()}
          fallback={
            <div class="p-4">
              <LoadingText label="AUDITING…" />
            </div>
          }
        >
          <Show
            when={(groups() ?? []).length}
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
                {(groups() ?? []).length} near-duplicate cluster(s) detected.
                Delete the redundant members.
              </Text>
              <For each={groups() ?? []}>
                {(group) => (
                  <div class="border border-line">
                    <div class="flex items-center justify-between border-b border-line bg-raised px-4 py-2">
                      <Text variant="label" tone="dim">
                        SIMILARITY
                      </Text>
                      <Text variant="readout" tone="warn">
                        {num(group.similarity * 100, 0)}%
                      </Text>
                    </div>
                    <Stack gap={2} class="p-4">
                      <For each={group.memories}>
                        {(m, i) => (
                          <>
                            <Show when={i() > 0}>
                              <Divider />
                            </Show>
                            <Row justify="between" align="start" gap={3}>
                              <Text variant="body" class="min-w-0 break-words">
                                {m.content}
                              </Text>
                              <Button
                                variant="danger"
                                size="sm"
                                leading="trash"
                                onClick={() => deleteFromGroup(m)}
                              >
                                DELETE
                              </Button>
                            </Row>
                          </>
                        )}
                      </For>
                    </Stack>
                  </div>
                )}
              </For>
            </Stack>
          </Show>
        </Show>
      </Modal>
    </Stack>
  );
}
