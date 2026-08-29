import {
  createEffect,
  createResource,
  createSignal,
  Match,
  Show,
  Switch,
  untrack,
  type JSX,
} from "solid-js";
import { EmptyState } from "~/ui";
import { fetchSnapshotFiles } from "../data";
import type { ViewSnapshotRef } from "../model";
import type { ViewItem, PriorVersion } from "../viewport";
import { ViewLiveContent } from "./ViewLiveContent";
import { ViewVersionContent } from "./ViewVersionContent";
import { ViewSnapshotPreview } from "./ViewSnapshotPreview";
import { ViewSnapshotCode } from "./ViewSnapshotCode";

/**
 * Renders the selected version on stage in the chosen mode. The live head is a persistent
 * arm — keyed only on its URL (in `SandboxedFrame`), so minting a new version on the same
 * running server relabels without reloading the iframe. Captured-version content (its
 * static preview / auto entry HTML, and its CODE tree) lives in `SnapshotStage`, which is
 * **remounted per snapshot id**: the file list, entry path, and auth blob URLs are all
 * derived from the snapshot, so a fresh mount per version makes a stale-id/new-files
 * desync (which produced 404s and revoked-blob frames) impossible. The frontend only
 * mounts what the entry describes; it decides nothing.
 */
export function ViewStage(props: {
  entry: ViewItem;
  mode: "preview" | "code";
  /** Manual reload nonce — bumping it reloads the live/preview iframe in place. */
  reloadKey: number;
  /** Prior snapshots the selected entry's CODE can diff against (oldest → newest). */
  priorVersions: PriorVersion[];
  /** Operator font-size step (-2..+2) and soft-wrap preference, persisted by the
   *  panel and threaded down to whichever content/code view is on stage. */
  fontStep?: number;
  softWrap?: boolean;
}): JSX.Element {
  return (
    <Switch>
      {/* PREVIEW — live head first (live = the latest version's preview). Persistent
          across version relabels so the running server's iframe isn't torn down. */}
      <Match when={props.mode === "preview" && props.entry.live}>
        {(live) => (
          <ViewLiveContent
            live={live()}
            reloadKey={props.reloadKey}
            fontStep={props.fontStep}
          />
        )}
      </Match>

      {/* PREVIEW (non-live) + CODE for a captured version — remounted per snapshot id. */}
      <Match when={props.entry.snapshot}>
        {(snapshot) => (
          <Show keyed when={snapshot().snapshotId}>
            <SnapshotStage
              snapshot={snapshot()}
              mode={props.mode}
              reloadKey={props.reloadKey}
              priorVersions={props.priorVersions}
              fontStep={props.fontStep}
              softWrap={props.softWrap}
            />
          </Show>
        )}
      </Match>

      {/* CODE for a standalone live head with no captured version yet. */}
      <Match when={props.mode === "code" && props.entry.live}>
        <EmptyState
          message="No source"
          hint="The live server has no captured version yet."
        />
      </Match>
    </Switch>
  );
}

/**
 * One captured version on stage. Fresh per snapshot (the parent keys it on the snapshot
 * id), so its file list, selected file, and the CODE compare base all start clean and can
 * never carry over from another version. The file list and selected file are owned here,
 * not in the per-mode child: the stage stays mounted across PREVIEW/CODE toggles (which
 * only swap the child), so the list is fetched once and the file pick survives a flip.
 */
function SnapshotStage(props: {
  snapshot: ViewSnapshotRef;
  mode: "preview" | "code";
  reloadKey: number;
  priorVersions: PriorVersion[];
  fontStep?: number;
  softWrap?: boolean;
}): JSX.Element {
  const [files, { refetch: refetchFiles }] = createResource(
    () => props.snapshot.snapshotId,
    fetchSnapshotFiles,
  );
  const [selectedPath, setSelectedPath] = createSignal<string | null>(null);

  // Default-select the first file once the list resolves and nothing is picked.
  createEffect(() => {
    const list = files();
    if (!list || list.length === 0) return;
    if (untrack(selectedPath) === null) setSelectedPath(list[0].path);
  });

  return (
    <Switch>
      {/* PREVIEW — the version's stamped static file, else its auto-picked entry HTML. */}
      <Match when={props.mode === "preview" && props.snapshot.preview}>
        <ViewVersionContent
          preview={props.snapshot.preview!}
          title={props.snapshot.title ?? "Version"}
          reloadKey={props.reloadKey}
          fontStep={props.fontStep}
          softWrap={props.softWrap}
        />
      </Match>
      <Match when={props.mode === "preview"}>
        <ViewSnapshotPreview
          snapshot={props.snapshot}
          files={files}
          onRetryFiles={() => void refetchFiles()}
          reloadKey={props.reloadKey}
          fontStep={props.fontStep}
        />
      </Match>

      {/* CODE — the version's workspace tree (with a diff-against control). */}
      <Match when={props.mode === "code"}>
        <ViewSnapshotCode
          snapshot={props.snapshot}
          files={files}
          onRetryFiles={() => void refetchFiles()}
          selectedPath={selectedPath()}
          onSelectPath={setSelectedPath}
          priorVersions={props.priorVersions}
          fontStep={props.fontStep}
          softWrap={props.softWrap}
        />
      </Match>
    </Switch>
  );
}
