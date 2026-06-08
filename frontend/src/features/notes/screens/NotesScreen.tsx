import {
  createEffect,
  createMemo,
  createSignal,
  For,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import { createStore, produce } from "solid-js/store";
import {
  Button,
  Checkbox,
  EmptyState,
  Input,
  InstrumentBand,
  ListToolbar,
  LoadingText,
  Modal,
  PageHeader,
  Panel,
  ProgressBar,
  Row,
  Stack,
  StatusFlag,
  Tabs,
  Text,
  Textarea,
  confirm,
  toast,
} from "~/ui";
import { createListView } from "~/lib/list";
import { relativeTime, timestamp } from "~/lib/format";
import { useNotes } from "../data";
import type { Note, NoteTone } from "../model";

const TONE_STATUS: Record<
  NoteTone,
  "idle" | "nominal" | "info" | "warn" | "alert"
> = {
  dim: "idle",
  nominal: "nominal",
  info: "info",
  warn: "warn",
  alert: "alert",
};

const ALL_LABELS = ["all", "engineering", "ops", "work", "personal", "ideas"];

let noteCounter = 100;

export function NotesScreen(): JSX.Element {
  const notesResource = useNotes();
  const [notes, setNotes] = createStore<Note[]>([]);
  const [seeded, setSeeded] = createSignal(false);

  // Seed store from resource once ready
  createEffect(() => {
    const data = notesResource();
    if (data && !seeded()) {
      setNotes(data.slice());
      setSeeded(true);
    }
  });

  const [labelFilter, setLabelFilter] = createSignal("all");
  const [newNoteOpen, setNewNoteOpen] = createSignal(false);
  const [editingNote, setEditingNote] = createSignal<Note | null>(null);

  // New note form
  const [formTitle, setFormTitle] = createSignal("");
  const [formBody, setFormBody] = createSignal("");
  const [formLabel, setFormLabel] = createSignal("");
  const [formDue, setFormDue] = createSignal("");
  const [formChecklist, setFormChecklist] = createSignal("");

  // Dirty tracking — true once any field has changed since the form was opened
  const [dirty, setDirty] = createSignal(false);

  function markDirty<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setDirty(true);
    };
  }

  const labelFiltered = createMemo(() => {
    const lf = labelFilter();
    return notes.filter((n) => lf === "all" || n.label === lf);
  });

  const view = createListView({
    source: labelFiltered,
    search: (n) => `${n.title} ${n.body}`,
    sorts: {
      recent: {
        label: "UPDATED",
        compare: (a, b) => a.updatedAt.localeCompare(b.updatedAt),
      },
      title: {
        label: "TITLE",
        compare: (a, b) => a.title.localeCompare(b.title),
      },
    },
    initialSort: "recent",
    initialDir: "desc",
  });

  const filtered = view.items;
  // Partition pinned/unpinned in one pass instead of two filter walks.
  const partition = createMemo(() => {
    const pinnedNotes: Note[] = [];
    const unpinnedNotes: Note[] = [];
    for (const n of filtered()) {
      (n.pinned ? pinnedNotes : unpinnedNotes).push(n);
    }
    return { pinned: pinnedNotes, unpinned: unpinnedNotes };
  });
  const pinned = () => partition().pinned;
  const unpinned = () => partition().unpinned;

  const pinnedCount = () => notes.filter((n) => n.pinned).length;
  const withDueCount = () => notes.filter((n) => n.dueAt).length;
  const checklistCount = () =>
    notes.filter((n) => n.checklist && n.checklist.length > 0).length;

  function toggleChecklistItem(noteId: string, itemId: string) {
    const idx = notes.findIndex((n) => n.id === noteId);
    if (idx < 0) return;
    setNotes(
      produce((ns) => {
        const item = ns[idx].checklist?.find((c) => c.id === itemId);
        if (item) item.done = !item.done;
      }),
    );
  }

  function togglePin(noteId: string) {
    const idx = notes.findIndex((n) => n.id === noteId);
    if (idx < 0) return;
    setNotes(
      produce((ns) => {
        ns[idx].pinned = !ns[idx].pinned;
      }),
    );
  }

  function openNew() {
    setFormTitle("");
    setFormBody("");
    setFormLabel("");
    setFormDue("");
    setFormChecklist("");
    setEditingNote(null);
    setDirty(false);
    setNewNoteOpen(true);
  }

  function openEdit(note: Note) {
    setFormTitle(note.title);
    setFormBody(note.body);
    setFormLabel(note.label ?? "");
    setFormDue(note.dueAt ? note.dueAt.slice(0, 16) : "");
    setFormChecklist(note.checklist?.map((c) => c.text).join("\n") ?? "");
    setEditingNote(note);
    setDirty(false);
    setNewNoteOpen(true);
  }

  async function handleCancel() {
    if (dirty()) {
      const ok = await confirm({
        title: "Discard changes?",
        detail: "Your unsaved edits will be lost.",
        confirmLabel: "DISCARD",
        cancelLabel: "KEEP EDITING",
        tone: "alert",
      });
      if (!ok) return;
    }
    setNewNoteOpen(false);
  }

  async function deleteNote(note: Note) {
    const ok = await confirm({
      title: `Delete "${note.title}"?`,
      detail: "This cannot be undone.",
      confirmLabel: "DELETE",
      tone: "alert",
    });
    if (!ok) return;

    const snapshot = notes.slice();
    const idx = notes.findIndex((n) => n.id === note.id);
    if (idx < 0) return;

    setNotes(produce((ns) => ns.splice(idx, 1)));

    toast.success("Note deleted", {
      action: {
        label: "UNDO",
        onClick: () =>
          setNotes(
            produce((ns) => ns.splice(idx, 0, ...snapshot.slice(idx, idx + 1))),
          ),
      },
    });
  }

  function saveNote() {
    const id = editingNote()?.id ?? `note-mock-${++noteCounter}`;
    const now = new Date().toISOString();
    const checklistLines = formChecklist()
      .split("\n")
      .map((t) => t.trim())
      .filter(Boolean);

    const existing = notes.findIndex((n) => n.id === id);
    if (existing >= 0) {
      setNotes(
        produce((ns) => {
          const n = ns[existing];
          n.title = formTitle();
          n.body = formBody();
          n.label = formLabel() || undefined;
          n.dueAt = formDue() || undefined;
          n.updatedAt = now;
          if (checklistLines.length > 0) {
            n.checklist = checklistLines.map((text, i) => ({
              id: `cl-new-${i}`,
              text,
              done: false,
            }));
          } else {
            n.checklist = undefined;
          }
        }),
      );
    } else {
      const newNote: Note = {
        id,
        title: formTitle() || "UNTITLED",
        body: formBody(),
        label: formLabel() || undefined,
        tone: "dim",
        pinned: false,
        dueAt: formDue() || undefined,
        createdAt: now,
        updatedAt: now,
        checklist:
          checklistLines.length > 0
            ? checklistLines.map((text, i) => ({
                id: `cl-new-${i}`,
                text,
                done: false,
              }))
            : undefined,
      };
      setNotes(
        produce((ns) => {
          ns.push(newNote);
        }),
      );
    }
    const wasEditing = editingNote() !== null;
    setNewNoteOpen(false);
    toast.success(wasEditing ? "Note updated" : "Note saved");
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="NOTES"
        subtitle="Pinned notes, checklists, and reminders."
        assetId="PROD-NOTE-01.0"
        actions={
          <Button variant="primary" leading="plus" onClick={openNew}>
            NEW NOTE
          </Button>
        }
      />

      <Suspense fallback={<LoadingText label="LOADING NOTES" />}>
        <InstrumentBand
          items={[
            { label: "TOTAL", value: String(notes.length) },
            { label: "PINNED", value: String(pinnedCount()) },
            { label: "WITH DUE DATE", value: String(withDueCount()) },
            { label: "WITH CHECKLIST", value: String(checklistCount()) },
            { label: "SHOWING", value: String(filtered().length) },
          ]}
        />
      </Suspense>

      <Tabs
        items={ALL_LABELS.map((l) => ({ value: l, label: l.toUpperCase() }))}
        value={labelFilter()}
        onChange={setLabelFilter}
      />

      <ListToolbar
        query={view.query()}
        onQueryChange={view.setQuery}
        placeholder="Search notes by title or body…"
        sortKey={view.sortKey()}
        sortOptions={view.sortOptions}
        onSortChange={view.setSort}
        dir={view.dir()}
        onToggleDir={view.toggleDir}
        count={view.count()}
        total={view.total()}
      />

      <Suspense fallback={<LoadingText label="LOADING" />}>
        <Show
          when={filtered().length}
          fallback={
            <EmptyState
              icon="note"
              message="NO NOTES"
              hint={
                view.isFiltered()
                  ? "No notes match your search."
                  : "No notes match the current filter."
              }
              action={
                <Button variant="default" onClick={openNew}>
                  ADD NOTE
                </Button>
              }
            />
          }
        >
          <Stack gap={6}>
            {/* Pinned */}
            <Show when={pinned().length}>
              <Stack gap={3}>
                <Row gap={2} align="center">
                  <Text variant="label" tone="dim">
                    PINNED
                  </Text>
                  <div class="flex-1 border-t border-line" />
                </Row>
                <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                  <For each={pinned()}>
                    {(note) => (
                      <NoteCard
                        note={note}
                        onToggleItem={toggleChecklistItem}
                        onPin={togglePin}
                        onEdit={openEdit}
                        onDelete={deleteNote}
                      />
                    )}
                  </For>
                </div>
              </Stack>
            </Show>

            {/* Unpinned */}
            <Show when={unpinned().length}>
              <Stack gap={3}>
                <Show when={pinned().length}>
                  <Row gap={2} align="center">
                    <Text variant="label" tone="dim">
                      OTHER
                    </Text>
                    <div class="flex-1 border-t border-line" />
                  </Row>
                </Show>
                <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                  <For each={unpinned()}>
                    {(note) => (
                      <NoteCard
                        note={note}
                        onToggleItem={toggleChecklistItem}
                        onPin={togglePin}
                        onEdit={openEdit}
                        onDelete={deleteNote}
                      />
                    )}
                  </For>
                </div>
              </Stack>
            </Show>
          </Stack>
        </Show>
      </Suspense>

      {/* New / edit note modal */}
      <Modal
        open={newNoteOpen()}
        onClose={handleCancel}
        title={editingNote() ? "EDIT NOTE" : "NEW NOTE"}
        class="max-w-xl"
        footer={
          <Row gap={2}>
            <Button variant="ghost" onClick={handleCancel}>
              CANCEL
            </Button>
            <Button variant="primary" leading="check" onClick={saveNote}>
              SAVE
            </Button>
          </Row>
        }
      >
        <Stack gap={4}>
          <Input
            label="TITLE"
            value={formTitle()}
            onInput={(e) => markDirty(setFormTitle)(e.currentTarget.value)}
            placeholder="Note title"
          />
          <Textarea
            label="BODY"
            rows={6}
            value={formBody()}
            onInput={(e) => markDirty(setFormBody)(e.currentTarget.value)}
          />
          <Row gap={4}>
            <Input
              label="LABEL"
              value={formLabel()}
              onInput={(e) => markDirty(setFormLabel)(e.currentTarget.value)}
              placeholder="e.g. engineering"
              class="flex-1"
            />
            <Input
              label="DUE DATE"
              type="datetime-local"
              value={formDue()}
              onInput={(e) => markDirty(setFormDue)(e.currentTarget.value)}
              class="flex-1"
            />
          </Row>
          <Textarea
            label="CHECKLIST ITEMS (one per line)"
            rows={4}
            value={formChecklist()}
            onInput={(e) => markDirty(setFormChecklist)(e.currentTarget.value)}
          />
        </Stack>
      </Modal>
    </Stack>
  );
}

interface NoteCardProps {
  note: Note;
  onToggleItem: (noteId: string, itemId: string) => void;
  onPin: (noteId: string) => void;
  onEdit: (note: Note) => void;
  onDelete: (note: Note) => void;
}

function NoteCard(props: NoteCardProps): JSX.Element {
  const { note } = props;
  const [checklistExpanded, setChecklistExpanded] = createSignal(false);
  const doneCount = () => note.checklist?.filter((c) => c.done).length ?? 0;
  const totalItems = () => note.checklist?.length ?? 0;
  const progress = () =>
    totalItems() > 0 ? Math.round((doneCount() / totalItems()) * 100) : 0;
  const visibleItems = () =>
    checklistExpanded()
      ? (note.checklist ?? [])
      : (note.checklist ?? []).slice(0, 4);
  const hiddenCount = () => Math.max(0, totalItems() - 4);

  return (
    <Panel
      state={note.pinned ? "active" : "default"}
      class="flex flex-col gap-3"
    >
      <Row justify="between" align="start">
        <Stack gap={1} class="min-w-0 flex-1">
          <Text variant="readout" tone="bright" class="truncate">
            {note.title}
          </Text>
          <Row gap={2} wrap>
            <Show when={note.label}>
              <StatusFlag status={note.tone ? TONE_STATUS[note.tone] : "idle"}>
                {note.label!.toUpperCase()}
              </StatusFlag>
            </Show>
            <Show when={note.pinned}>
              <StatusFlag status="info">PINNED</StatusFlag>
            </Show>
            <Show when={note.reminderAt}>
              <StatusFlag status="warn">REMINDER</StatusFlag>
            </Show>
          </Row>
        </Stack>
        <Row gap={1}>
          <Button
            variant="ghost"
            size="sm"
            leading="edit"
            onClick={() => props.onEdit(note)}
          />
          <Button
            variant="ghost"
            size="sm"
            leading={note.pinned ? "minus" : "plus"}
            onClick={() => props.onPin(note.id)}
          />
          <Button
            variant="ghost"
            size="sm"
            leading="trash"
            onClick={() => props.onDelete(note)}
          />
        </Row>
      </Row>

      <Text variant="body" tone="dim" class="line-clamp-3 whitespace-pre-wrap">
        {note.body}
      </Text>

      <Show when={totalItems() > 0}>
        <Stack gap={2}>
          <Row justify="between" align="center">
            <Text variant="label" tone="dim">
              CHECKLIST
            </Text>
            <Text variant="micro" tone="dim">
              {doneCount()}/{totalItems()}
            </Text>
          </Row>
          <ProgressBar value={progress()} tone="nominal" />
          <Stack gap={1}>
            <For each={visibleItems()}>
              {(item) => (
                <Checkbox
                  checked={item.done}
                  onChange={() => props.onToggleItem(note.id, item.id)}
                  label={item.text}
                />
              )}
            </For>
            <Show when={hiddenCount() > 0}>
              <button
                type="button"
                onClick={() => setChecklistExpanded((v) => !v)}
                class="self-start text-label uppercase tracking-label text-dim transition-colors hover:text-bright"
              >
                {checklistExpanded()
                  ? "Show less"
                  : `+${hiddenCount()} more items`}
              </button>
            </Show>
          </Stack>
        </Stack>
      </Show>

      <Row justify="between" align="center" class="border-t border-line pt-2">
        <Show when={note.dueAt}>
          <Row gap={1} align="center">
            <Text variant="micro" tone="dim">
              DUE
            </Text>
            <Text variant="micro" tone="warn">
              {timestamp(note.dueAt!)}
            </Text>
          </Row>
        </Show>
        <Text variant="micro" tone="dim" class="ml-auto">
          {relativeTime(note.updatedAt)}
        </Text>
      </Row>
    </Panel>
  );
}
