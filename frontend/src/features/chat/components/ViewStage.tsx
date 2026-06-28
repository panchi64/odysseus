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
 * server (when live), else the version's stamped static file rendered by kind, else its
 * auto-picked entry HTML page; CODE shows the version's workspace tree (with a
 * diff-against control). A standalone live head with no captured version has no tree, so
 * its CODE is empty. The frontend only mounts what the entry describes; it decides nothing.
 *
 * A version's file list and selected file are owned here, not in the per-mode child:
 * the stage stays mounted across PREVIEW/CODE toggles (which only swap the child), so
 * the list is fetched once and the operator's file pick is kept when they flip modes.
 */
export function ViewStage(props: {
  entry: ViewItem;
  mode: "preview" | "code";
  /** Manual reload nonce — bumping it reloads the live/preview iframe in place. */
  reloadKey: number;
  /** Prior snapshots the selected entry's CODE can diff against (oldest → newest). */
  priorVersions: PriorVersion[];
}): JSX.Element {
  const snapshotId = (): string | undefined => props.entry.snapshot?.snapshotId;
  const [files] = createResource(snapshotId, fetchSnapshotFiles);
  const [selectedPath, setSelectedPath] = createSignal<string | null>(null);

  // The stage is reused across versions (it no longer remounts), so reset the file
  // pick when the version changes — the new tree starts at its own first file.
  createEffect(() => {
    snapshotId();
    untrack(() => setSelectedPath(null));
  });
  // Default-select the first file once the list resolves and nothing is picked.
  createEffect(() => {
    const list = files();
    if (!list || list.length === 0) return;
    if (untrack(selectedPath) === null) setSelectedPath(list[0].path);
  });

  return (
    <Switch>
      {/* PREVIEW — live head first (live = the latest version's preview), else the
          version's stamped static file, else its auto-picked entry HTML page. */}
      <Match when={props.mode === "preview" && props.entry.live}>
        <ViewLiveContent live={props.entry.live!} reloadKey={props.reloadKey} />
      </Match>
      <Match when={props.mode === "preview" && props.entry.snapshot?.preview}>
        <ViewVersionContent
          preview={props.entry.snapshot!.preview!}
          title={props.entry.snapshot!.title ?? "Version"}
          reloadKey={props.reloadKey}
        />
      </Match>
      <Match when={props.mode === "preview" && props.entry.snapshot}>
        <ViewSnapshotPreview
          snapshot={props.entry.snapshot!}
          files={files}
          reloadKey={props.reloadKey}
        />
      </Match>

      {/* CODE — the version's workspace tree (live = its latest version), else NO
          SOURCE for a standalone live head with no captured version yet. */}
      <Match when={props.mode === "code" && props.entry.snapshot}>
        <ViewSnapshotCode
          snapshot={props.entry.snapshot!}
          files={files}
          selectedPath={selectedPath()}
          onSelectPath={setSelectedPath}
          priorVersions={props.priorVersions}
        />
      </Match>
      <Match when={props.mode === "code" && props.entry.live}>
        <EmptyState
          message="NO SOURCE"
          hint="The live server has no captured version yet."
        />
      </Match>
    </Switch>
  );
}
