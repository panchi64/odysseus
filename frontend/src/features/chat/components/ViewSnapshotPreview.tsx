import { createMemo, Match, Switch, type JSX, type Resource } from "solid-js";
import { useAuthedBlobUrl } from "~/lib/api";
import { EmptyState, ErrorState, LoadingText } from "~/ui";
import { snapshotFilePath } from "../data";
import type { SnapshotFile, ViewSnapshotRef } from "../model";
import { pickEntryHtml } from "../viewport";
import { SandboxedFrame } from "./SandboxedFrame";

/**
 * Renders a workspace snapshot's PREVIEW — its entry HTML page (index.html, else the
 * first HTML file) rendered in an opaque-origin sandboxed iframe. A snapshot is a
 * static capture, not a live server, so assets resolve from the captured bytes. When
 * the snapshot has no HTML page there is nothing to render; the operator uses CODE to
 * browse its files instead. The file list is owned by the stage and passed in, so
 * flipping PREVIEW/CODE doesn't refetch it.
 */
export function ViewSnapshotPreview(props: {
  snapshot: ViewSnapshotRef;
  files: Resource<SnapshotFile[]>;
  /** Manual reload nonce — bumping it reloads the framed entry page in place. */
  reloadKey: number;
}): JSX.Element {
  const entry = createMemo(() => {
    const list = props.files();
    return list ? pickEntryHtml(list) : undefined;
  });
  const renderUrl = useAuthedBlobUrl(() => {
    const path = entry();
    return path ? snapshotFilePath(props.snapshot.snapshotId, path) : undefined;
  });

  return (
    <Switch fallback={<LoadingText label="LOADING PREVIEW…" />}>
      <Match when={props.files.error}>
        <ErrorState message="Could not load this version." />
      </Match>
      <Match when={props.files() && !entry()}>
        <EmptyState
          message="NO PREVIEW"
          hint="This version has no HTML page — use CODE to browse its files."
        />
      </Match>
      <Match when={renderUrl.error}>
        <ErrorState message="Could not render this version." />
      </Match>
      <Match when={renderUrl()}>
        {(url) => (
          <SandboxedFrame
            src={url()}
            title={entry()!}
            reloadKey={props.reloadKey}
          />
        )}
      </Match>
    </Switch>
  );
}
