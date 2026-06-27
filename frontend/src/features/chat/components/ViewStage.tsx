import {
  createEffect,
  createResource,
  createSignal,
  Match,
  Switch,
  untrack,
  type JSX,
} from "solid-js";
import { EmptyState } from "~/ui";
import { fetchSnapshotFiles } from "../data";
import type { ViewItem, PriorVersion } from "../viewport";
import { ViewLiveContent } from "./ViewLiveContent";
import { ViewVersionContent } from "./ViewVersionContent";
import { ViewSnapshotPreview } from "./ViewSnapshotPreview";
import { ViewSnapshotCode } from "./ViewSnapshotCode";

/**
 * Renders the selected version on stage in the chosen mode. PREVIEW shows the running
 * server (when live), else the rendered HTML / artifact; CODE shows the snapshot's
 * files (with a diff-against control) or the artifact's source. A live head with no
 * snapshot has no captured source, so its CODE is empty. The frontend only mounts what
 * the entry's content source describes; it decides nothing.
 *
 * A snapshot's file list and selected file are owned here, not in the per-mode child:
 * the stage stays mounted across PREVIEW/CODE toggles (which only swap the child), so
 * the list is fetched once and the operator's file pick is kept when they flip modes.
 */
export function ViewStage(props: {
  entry: ViewItem;
  mode: "preview" | "code";
  /** Prior snapshots the selected entry's CODE can diff against (oldest → newest). */
  priorVersions: PriorVersion[];
}): JSX.Element {
  const snapshotId = (): string | undefined => props.entry.snapshot?.snapshotId;
  const [files] = createResource(snapshotId, fetchSnapshotFiles);
  const [selectedPath, setSelectedPath] = createSignal<string | null>(null);

  // Default-select the first file once the list resolves and nothing is picked.
  createEffect(() => {
    const list = files();
    if (!list || list.length === 0) return;
    if (untrack(selectedPath) === null) setSelectedPath(list[0].path);
  });

  return (
    <Switch>
      {/* PREVIEW — live server first (live = the latest snapshot's preview). */}
      <Match when={props.mode === "preview" && props.entry.live}>
        <ViewLiveContent live={props.entry.live!} />
      </Match>
      <Match when={props.mode === "preview" && props.entry.snapshot}>
        <ViewSnapshotPreview snapshot={props.entry.snapshot!} files={files} />
      </Match>
      <Match when={props.mode === "preview" && props.entry.version}>
        <ViewVersionContent version={props.entry.version!} mode="preview" />
      </Match>

      {/* CODE — a snapshot's files (live = its latest snapshot), else artifact source. */}
      <Match when={props.mode === "code" && props.entry.snapshot}>
        <ViewSnapshotCode
          snapshot={props.entry.snapshot!}
          files={files}
          selectedPath={selectedPath()}
          onSelectPath={setSelectedPath}
          priorVersions={props.priorVersions}
        />
      </Match>
      <Match when={props.mode === "code" && props.entry.version}>
        <ViewVersionContent version={props.entry.version!} mode="code" />
      </Match>
      <Match when={props.mode === "code" && props.entry.live}>
        <EmptyState
          message="NO SOURCE"
          hint="The live server has no captured snapshot yet."
        />
      </Match>
    </Switch>
  );
}
