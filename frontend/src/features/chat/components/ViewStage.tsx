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
import type { ViewDocumentRef, ViewSnapshotRef } from "../model";
import type { ViewItem, PriorVersion } from "../viewport";
import { ViewLiveContent } from "./ViewLiveContent";
import { ViewVersionContent } from "./ViewVersionContent";
import { ViewSnapshotPreview } from "./ViewSnapshotPreview";
import { ViewSnapshotCode } from "./ViewSnapshotCode";
import { ViewDocumentContent } from "./ViewDocumentContent";
import { ViewDocumentCode } from "./ViewDocumentCode";

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
  /** Prior committed versions of the selected document, for its CODE diff (oldest →
   *  newest). Empty unless the entry is a document. */
  priorDocuments: ViewDocumentRef[];
  /** Relays an inline document edit to the backend (SAVE mints a new version). */
  onSaveDocument: (documentId: string, body: string) => Promise<void>;
  onDocumentVersion: (
    documentId: string,
    body: string,
    version: number | null,
  ) => void;
  /** Operator font-size step (-2..+2) and soft-wrap preference, persisted by the
   *  panel and threaded down to whichever content/code view is on stage. */
  fontStep?: number;
  softWrap?: boolean;
}): JSX.Element {
  return (
    <Switch>
      {/* A document version — its markdown body as PREVIEW, raw source + diff as CODE.
          Only the latest *committed version of this document* is editable inline —
          gated on `documentIsLatest` (per-document), not the View's single global
          `isLatest` (which a document loses the moment any other document/snapshot
          mints a newer entry). The narrowed accessor (`doc()`) is only alive while
          this branch is selected, so a version switch that swaps `entry` to a
          non-document can't leave a stale deref of an `undefined` field behind
          (which would throw and blank the whole app). */}
      <Match when={props.entry.document}>
        {(doc) => (
          <Switch>
            <Match when={props.mode === "preview"}>
              {/* Remount per document version: an in-flight inline edit belongs to the
                  version it started on, so when a newer version arrives (e.g. the agent
                  commits while the operator is editing) the editor resets rather than
                  letting SAVE write a stale draft onto the wrong base. */}
              <Show keyed when={`${doc().documentId}-${doc().version}`}>
                <ViewDocumentContent
                  document={doc()}
                  editable={
                    Boolean(props.entry.documentIsLatest) && doc().version >= 1
                  }
                  onSave={props.onSaveDocument}
                  onDocumentVersion={props.onDocumentVersion}
                  fontStep={props.fontStep}
                  softWrap={props.softWrap}
                />
              </Show>
            </Match>
            <Match when={props.mode === "code"}>
              <ViewDocumentCode
                document={doc()}
                priorVersions={props.priorDocuments}
                fontStep={props.fontStep}
                softWrap={props.softWrap}
              />
            </Match>
          </Switch>
        )}
      </Match>

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
          message="NO SOURCE"
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
