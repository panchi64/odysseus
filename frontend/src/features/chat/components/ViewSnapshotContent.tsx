import {
  createEffect,
  createMemo,
  createResource,
  createSignal,
  For,
  Match,
  Show,
  Switch,
  untrack,
  type JSX,
} from "solid-js";
import { useAuthedBlobUrl } from "~/lib/api";
import {
  CodeBlock,
  DiffView,
  EmptyState,
  ErrorState,
  ListRow,
  LoadingText,
  Resource,
  Tabs,
  Text,
  type TabItem,
  type TextTone,
} from "~/ui";
import {
  fetchSnapshotDiffs,
  fetchSnapshotFileText,
  fetchSnapshotFiles,
  snapshotFilePath,
} from "../data";
import type { SnapshotFile, ViewSnapshotRef } from "../model";
import { SandboxedFrame } from "./SandboxedFrame";

type Mode = "code" | "diff" | "rendered";

const MODE_TABS: TabItem[] = [
  { value: "code", label: "CODE" },
  { value: "diff", label: "DIFF" },
  { value: "rendered", label: "RENDERED" },
];

/** The tone + single-letter marker for a file's change status. Kept monochrome —
 *  brightness separates changed (bright) from unchanged (dim), per the design
 *  system's color discipline; the two semantic accents are reserved for the diff,
 *  where add/remove genuinely carry meaning. The A/M/· marker does the rest. */
function statusTone(status: SnapshotFile["status"]): TextTone {
  return status === "unchanged" ? "dim" : "bright";
}
function statusMark(status: SnapshotFile["status"]): string {
  return status === "added" ? "A" : status === "modified" ? "M" : "·";
}

function isHtmlPath(path: string): boolean {
  return /\.html?$/i.test(path);
}

/**
 * Renders a workspace snapshot — a git-style, point-in-time capture of the agent's
 * sandbox tree. A left file list (with change-status markers) selects a file; a
 * mode switch shows its CODE, its unified DIFF, or — for HTML — a RENDERED preview.
 * The frontend only displays what the snapshot endpoints return; it decides nothing.
 */
export function ViewSnapshotContent(props: {
  snapshot: ViewSnapshotRef;
}): JSX.Element {
  const id = (): string => props.snapshot.snapshotId;
  const [files] = createResource(id, fetchSnapshotFiles);
  const [diffs] = createResource(id, fetchSnapshotDiffs);
  const [selectedPath, setSelectedPath] = createSignal<string | null>(null);
  const [mode, setMode] = createSignal<Mode>("code");

  // Default-select the first file once the list resolves and nothing is picked.
  createEffect(() => {
    const list = files();
    if (!list || list.length === 0) return;
    if (untrack(selectedPath) === null) setSelectedPath(list[0].path);
  });

  // The selected file's text — fetched only in CODE mode (auth-gated bytes → text).
  const [text] = createResource(
    () => {
      const path = selectedPath();
      return mode() === "code" && path ? ([id(), path] as const) : undefined;
    },
    ([snapshotId, path]) => fetchSnapshotFileText(snapshotId, path),
  );

  // The selected file's diff, from the already-loaded diff list.
  const selectedDiff = createMemo(() => {
    const path = selectedPath();
    return path ? diffs()?.find((d) => d.path === path) : undefined;
  });

  // RENDERED mode: an HTML file's bytes as a blob URL for the sandboxed frame
  // (held — no fetch — for non-HTML files or other modes).
  const renderUrl = useAuthedBlobUrl(() => {
    const path = selectedPath();
    return mode() === "rendered" && path && isHtmlPath(path)
      ? snapshotFilePath(id(), path)
      : undefined;
  });

  return (
    <div class="flex h-full min-h-0">
      {/* File tree — pick a file; its change status reads through tone. */}
      <div class="flex w-56 shrink-0 flex-col border-r border-line">
        <div class="border-b border-line px-3 py-2">
          <Text variant="micro" tone="dim">
            {props.snapshot.summary}
          </Text>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto">
          <Resource
            data={files}
            loadingLabel="LOADING FILES…"
            isEmpty={(rows) => rows.length === 0}
            emptyMessage="NO FILES"
          >
            {(rows) => (
              <For each={rows()}>
                {(file) => (
                  <ListRow
                    label={file.path}
                    leading="file"
                    selected={selectedPath() === file.path}
                    onClick={() => setSelectedPath(file.path)}
                    right={
                      <Text variant="micro" tone={statusTone(file.status)}>
                        {statusMark(file.status)}
                      </Text>
                    }
                  />
                )}
              </For>
            )}
          </Resource>
        </div>
      </div>

      {/* Content — CODE / DIFF / RENDERED for the selected file. */}
      <div class="flex min-w-0 flex-1 flex-col">
        <Tabs
          items={MODE_TABS}
          value={mode()}
          onChange={(v) => setMode(v as Mode)}
        />
        <div class="min-h-0 flex-1">
          <Show
            when={selectedPath()}
            fallback={
              <EmptyState
                message="NO FILE SELECTED"
                hint="Pick a file to view."
              />
            }
          >
            <Switch>
              <Match when={mode() === "code"}>
                <Switch fallback={<LoadingText label="LOADING FILE…" />}>
                  <Match when={text.error}>
                    <ErrorState message="Could not load this file." />
                  </Match>
                  <Match when={text() !== undefined}>
                    <CodeBlock code={text()!} />
                  </Match>
                </Switch>
              </Match>

              <Match when={mode() === "diff"}>
                <Show
                  when={selectedDiff()?.diff}
                  fallback={
                    <EmptyState
                      message="NO DIFF"
                      hint="This file is unchanged, or its diff is empty (e.g. binary)."
                    />
                  }
                >
                  <DiffView diff={selectedDiff()!.diff} />
                </Show>
              </Match>

              <Match when={mode() === "rendered"}>
                <Show
                  when={isHtmlPath(selectedPath()!)}
                  fallback={
                    <EmptyState
                      message="NO PREVIEW"
                      hint="Only HTML files render here; use CODE for everything else."
                    />
                  }
                >
                  <Switch fallback={<LoadingText label="LOADING PREVIEW…" />}>
                    <Match when={renderUrl.error}>
                      <ErrorState message="Could not render this file." />
                    </Match>
                    <Match when={renderUrl()}>
                      {(url) => (
                        <SandboxedFrame src={url()} title={selectedPath()!} />
                      )}
                    </Match>
                  </Switch>
                </Show>
              </Match>
            </Switch>
          </Show>
        </div>
      </div>
    </div>
  );
}
