import {
  createMemo,
  createResource,
  createSignal,
  For,
  Match,
  Show,
  Switch,
  type JSX,
  type Resource,
} from "solid-js";
import {
  CodeBlock,
  DiffView,
  EmptyState,
  ErrorState,
  ListRow,
  LoadingText,
  Resource as ResourceView,
  Select,
  Text,
  type SelectOption,
  type TextTone,
} from "~/ui";
import { fetchSnapshotDiffs, fetchSnapshotFileText } from "../data";
import type { SnapshotFile, ViewSnapshotRef } from "../model";
import type { PriorVersion } from "../viewport";

/** "Compare vs" value for plain code (no diff). */
const NO_DIFF = "";

/** The tone + single-letter marker for a file's change status. Kept monochrome —
 *  brightness separates changed (bright) from unchanged (dim), per the design
 *  system's color discipline; the two semantic accents are reserved for the diff. */
function statusTone(status: SnapshotFile["status"]): TextTone {
  return status === "unchanged" ? "dim" : "bright";
}
function statusMark(status: SnapshotFile["status"]): string {
  return status === "added" ? "A" : status === "modified" ? "M" : "·";
}

/**
 * Renders a workspace snapshot's CODE — a left file list (with change-status markers)
 * selecting a file, and a content pane showing either its full source or a unified
 * diff. A "Compare vs" control picks what to diff against: nothing (full code), or any
 * prior version, defaulting to the immediately-previous snapshot. The file list and the
 * selected file are owned by the stage and passed in, so they survive a PREVIEW/CODE
 * flip. The frontend only displays what the snapshot endpoints return; it decides nothing.
 */
export function ViewSnapshotCode(props: {
  snapshot: ViewSnapshotRef;
  files: Resource<SnapshotFile[]>;
  selectedPath: string | null;
  onSelectPath: (path: string) => void;
  /** Prior snapshots, chronological (oldest → newest); the last is the previous. */
  priorVersions: PriorVersion[];
}): JSX.Element {
  const id = (): string => props.snapshot.snapshotId;

  // The previous snapshot (default compare target), or "" when there is none.
  const previousId = createMemo(() => {
    const priors = props.priorVersions;
    return priors.length ? priors[priors.length - 1].id : NO_DIFF;
  });
  // Explicit compare pick; null = follow the default (previous snapshot).
  const [base, setBase] = createSignal<string | null>(null);
  const baseId = createMemo(() => base() ?? previousId());

  // Full source — only when comparing against nothing.
  const [text] = createResource(
    () => {
      const path = props.selectedPath;
      return baseId() === NO_DIFF && path ? ([id(), path] as const) : undefined;
    },
    ([snapshotId, path]) => fetchSnapshotFileText(snapshotId, path),
  );

  // Diffs against the chosen base — fetched lazily, only when one is selected.
  const [diffs] = createResource(
    () =>
      baseId() !== NO_DIFF ? ([id(), baseId()] as [string, string]) : undefined,
    ([snapshotId, b]) => fetchSnapshotDiffs(snapshotId, b),
  );
  const selectedDiff = createMemo(() => {
    const path = props.selectedPath;
    return path ? diffs()?.find((d) => d.path === path) : undefined;
  });

  // Compare options: full code, then each prior version (newest first).
  const compareOptions = createMemo<SelectOption[]>(() => [
    { value: NO_DIFF, label: "No diff · full code" },
    ...[...props.priorVersions]
      .reverse()
      .map((v) => ({ value: v.id, label: `Diff vs ${v.label}` })),
  ]);

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
          <ResourceView
            data={props.files}
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
                    selected={props.selectedPath === file.path}
                    onClick={() => props.onSelectPath(file.path)}
                    right={
                      <Text variant="micro" tone={statusTone(file.status)}>
                        {statusMark(file.status)}
                      </Text>
                    }
                  />
                )}
              </For>
            )}
          </ResourceView>
        </div>
      </div>

      {/* Content — full code or a diff against the chosen base. */}
      <div class="flex min-w-0 flex-1 flex-col">
        <div class="flex items-center gap-2 border-b border-line px-3 py-2">
          <Text variant="micro" tone="dim" class="shrink-0">
            COMPARE
          </Text>
          <Select
            aria-label="Compare against version"
            class="min-w-0 flex-1"
            options={compareOptions()}
            value={baseId()}
            onChange={(v) => setBase(v)}
          />
        </div>
        <div class="min-h-0 flex-1">
          <Show
            when={props.selectedPath}
            fallback={
              <EmptyState
                message="NO FILE SELECTED"
                hint="Pick a file to view."
              />
            }
          >
            <Switch>
              {/* Full code. */}
              <Match when={baseId() === NO_DIFF}>
                <Switch fallback={<LoadingText label="LOADING FILE…" />}>
                  <Match when={text.error}>
                    <ErrorState message="Could not load this file." />
                  </Match>
                  <Match when={text() !== undefined}>
                    <CodeBlock code={text()!} />
                  </Match>
                </Switch>
              </Match>

              {/* Diff against the chosen base. */}
              <Match when={baseId() !== NO_DIFF}>
                <Switch fallback={<LoadingText label="LOADING DIFF…" />}>
                  <Match when={diffs.error}>
                    <ErrorState message="Could not load this diff." />
                  </Match>
                  <Match when={diffs() && selectedDiff()?.diff}>
                    <DiffView diff={selectedDiff()!.diff} />
                  </Match>
                  <Match when={diffs() && !selectedDiff()?.diff}>
                    <EmptyState
                      message="NO DIFF"
                      hint="This file is unchanged from the selected version (or its diff is empty)."
                    />
                  </Match>
                </Switch>
              </Match>
            </Switch>
          </Show>
        </div>
      </div>
    </div>
  );
}
