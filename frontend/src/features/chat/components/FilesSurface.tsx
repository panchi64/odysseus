import {
  createEffect,
  createMemo,
  createResource,
  createSignal,
  on,
  onCleanup,
  Show,
  type JSX,
} from "solid-js";
import { api } from "~/lib/api";
import { Button, CodeBlock, EmptyState, LoadingText, Text } from "~/ui";
import {
  fetchSnapshotFiles,
  fetchSnapshotFileText,
  snapshotFilePath,
} from "../data";
import type { ViewItem } from "../viewport/viewItems";
import { extensionOf } from "../viewport/viewItems";
import { createDownloadSlot } from "../viewport/downloadRegistry";
import { isEdited, SnapshotFileTree } from "./SnapshotFileTree";

/** Below this the tree and a file cannot share a row, so the pane shows one at a
 *  time. `w-56` of tree against a 320px pane leaves ~96px for the file. */
const SIDE_BY_SIDE = 560;

/**
 * The workspace, browsable on its own.
 *
 * The same files have always been reachable — inside the View's CODE tab, which means
 * first having a View and then knowing to switch tabs. This is the workspace as a place
 * you go, which is what it is: a code thread's files are a thing the operator looks at
 * *while* reading the conversation, not a mode of an artifact viewer.
 *
 * **It is not the CODE tab moved.** That tab compares two captured versions and owns
 * the pickers for choosing them; this shows the latest snapshot's tree and the file you
 * pick. The one thing it adds is the filter the compare view had no need for: showing
 * only what this snapshot touched, which the backend already answers per file.
 *
 * **Narrow, it is one thing at a time.** A tree beside a file is the right layout when
 * there is room for both and an unreadable pair when there is not, so below
 * `SIDE_BY_SIDE` picking a file replaces the list and a back control returns to it.
 */
export function FilesSurface(props: {
  /** The thread's View items — the newest snapshot is the workspace as it stands. */
  items: () => ViewItem[];
  fontStep?: number;
  softWrap?: boolean;
}): JSX.Element {
  const snapshot = createMemo(
    () => [...props.items()].reverse().find((i) => i.snapshot)?.snapshot,
  );

  const [files, { refetch }] = createResource(
    () => snapshot()?.snapshotId,
    fetchSnapshotFiles,
  );
  const [selectedPath, setSelectedPath] = createSignal<string | null>(null);
  const [editedOnly, setEditedOnly] = createSignal(false);
  const [width, setWidth] = createSignal(0);
  const sideBySide = (): boolean => width() >= SIDE_BY_SIDE;

  // Default to the first file the operator is likely to want: the first *changed*
  // one when there is one, since a snapshot exists because something changed.
  createEffect(() => {
    const list = files();
    if (!list || list.length === 0) return;
    if (selectedPath() !== null) return;
    setSelectedPath((list.find(isEdited) ?? list[0]).path);
  });

  // A snapshot's file list is per snapshot, so a newer one invalidates the pick.
  // `defer` so this does not fire on mount and fight the default-select above —
  // it is only the *change* that clears.
  createEffect(
    on(
      () => snapshot()?.snapshotId,
      () => setSelectedPath(null),
      { defer: true },
    ),
  );

  const [text] = createResource(
    () => {
      const id = snapshot()?.snapshotId;
      const path = selectedPath();
      return id && path ? ([id, path] as const) : undefined;
    },
    ([id, path]) => fetchSnapshotFileText(id, path),
  );

  // Arm the panel's download with whatever file is on screen.
  const armDownload = createDownloadSlot();
  createEffect(() => {
    const id = snapshot()?.snapshotId;
    const path = selectedPath();
    if (!id || !path) {
      armDownload(null);
      return;
    }
    armDownload({
      name: path.split("/").pop() ?? path,
      getBlob: () => api.getBlob(snapshotFilePath(id, path)),
    });
  });

  const tree = (inline: boolean): JSX.Element => (
    <SnapshotFileTree
      files={files}
      onRetry={() => void refetch()}
      selectedPath={selectedPath()}
      onSelectPath={setSelectedPath}
      editedOnly={editedOnly()}
      inline={inline}
    />
  );

  const viewer = (): JSX.Element => (
    <div class="flex min-h-0 min-w-0 flex-1 flex-col">
      <Show when={!sideBySide()}>
        <div class="flex shrink-0 items-center gap-2 px-2 py-1.5">
          <Button
            variant="ghost"
            size="sm"
            leading="chevron-left"
            onClick={() => setSelectedPath(null)}
          >
            Files
          </Button>
          <Text variant="micro" tone="dim" class="min-w-0 truncate">
            {selectedPath()}
          </Text>
        </div>
      </Show>
      <div class="min-h-0 flex-1 overflow-auto">
        <Show when={text() !== undefined} fallback={<LoadingText />}>
          <CodeBlock
            code={text() ?? ""}
            lang={extensionOf(selectedPath()) ?? undefined}
            fontStep={props.fontStep}
            softWrap={props.softWrap}
          />
        </Show>
      </div>
    </div>
  );

  return (
    <div
      ref={(el) => {
        const observer = new ResizeObserver(() => setWidth(el.clientWidth));
        observer.observe(el);
        setWidth(el.clientWidth);
        // A surface is closed and reopened as often as the operator likes, and an
        // observer left running holds its detached element for the life of the tab.
        onCleanup(() => observer.disconnect());
      }}
      class="flex h-full min-h-0 flex-col"
    >
      <Show
        when={snapshot()}
        fallback={
          <EmptyState
            icon="file"
            message="No files yet"
            hint="The workspace appears here once the agent has captured a version of it."
          />
        }
      >
        <div class="flex shrink-0 items-center justify-between gap-2 px-3 py-2">
          <Text variant="label" tone="bright">
            Files
          </Text>
          <Button
            variant="ghost"
            size="sm"
            active={editedOnly()}
            aria-pressed={editedOnly()}
            onClick={() => setEditedOnly(!editedOnly())}
          >
            Edited only
          </Button>
        </div>
        <div class="flex min-h-0 flex-1">
          <Show
            when={sideBySide()}
            fallback={
              <Show when={selectedPath() !== null} fallback={tree(false)}>
                {viewer()}
              </Show>
            }
          >
            {tree(true)}
            {viewer()}
          </Show>
        </div>
      </Show>
    </div>
  );
}
