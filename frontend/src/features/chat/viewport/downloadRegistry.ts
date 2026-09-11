/**
 * Who has armed the panel's download control, and with what.
 *
 * The panel shows one DOWNLOAD button, but the thing it downloads is chosen several
 * layers down — by whichever content view currently has an artifact's bytes in hand. That
 * is a genuine cross-component seam, and it used to be a single module-level signal with a
 * bare setter: whoever called last won, and every caller's `onCleanup` cleared the signal
 * outright.
 *
 * **That works only while exactly one content view can be mounted.** Today that holds —
 * `SnapshotStage` picks one of the preview/version/code views with a `Switch`, so they are
 * mutually exclusive and the last writer is also the only writer. It stops holding the
 * moment the panel can show two surfaces at once, where an unconditional clear means a
 * view being torn down in one pane disarms the button for a view still mounted in another.
 *
 * So a claim is **owned**. `createDownloadSlot` hands a component its own slot, keyed by a
 * token nobody else holds: arming replaces only that component's entry, and standing down
 * — explicitly, or by being disposed — removes only that entry. A component cannot clear
 * another's claim, and cannot forget to release its own.
 *
 * Which of several live claims the button follows is deliberately left as "the most
 * recently armed". With one pane that is the only one; with several it is a placeholder
 * for the real answer, which is the focused surface's — a question this module cannot
 * answer yet because there are no surfaces.
 */

import { createSignal, onCleanup } from "solid-js";

/** A file the panel's DOWNLOAD control can fetch on demand. `getBlob` is a thunk
 *  because the bytes are usually already in hand and should not be re-fetched, but
 *  the control must not depend on that. */
export interface ActiveDownload {
  name: string;
  getBlob: () => Promise<Blob>;
}

/** One component's claim. Call with a file to arm it, or `null` to stand down while
 *  staying mounted (a code view with no file selected). Released automatically when
 *  the owning component is disposed. */
export type DownloadSlot = (download: ActiveDownload | null) => void;

/** Insertion-ordered, so the last entry is the most recently armed claim. Held in a
 *  signal and replaced rather than mutated, mirroring the persisted-map idiom in
 *  `viewport/persistence.ts` — Solid tracks the reference, not the contents. */
const [claims, setClaims] = createSignal<ReadonlyMap<number, ActiveDownload>>(
  new Map(),
);

let nextToken = 0;

/** Claim a download slot for the calling component, released on its cleanup. */
export function createDownloadSlot(): DownloadSlot {
  const token = nextToken++;

  const release = (): void => {
    setClaims((prev) => {
      if (!prev.has(token)) return prev;
      const next = new Map(prev);
      next.delete(token);
      return next;
    });
  };

  onCleanup(release);

  return (download) => {
    if (download === null) {
      release();
      return;
    }
    setClaims((prev) => {
      const next = new Map(prev);
      // Delete before set so re-arming moves this claim to the end — plain Map key
      // order is insertion order, and "most recently armed" is read off it.
      next.delete(token);
      next.set(token, download);
      return next;
    });
  };
}

/** The download the panel's control currently offers, or null when nothing is armed. */
export function activeDownload(): ActiveDownload | null {
  const map = claims();
  if (map.size === 0) return null;
  let last: ActiveDownload | null = null;
  for (const entry of map.values()) last = entry;
  return last;
}

/** Fetch and save whatever is armed. A no-op when nothing is — the control is
 *  disabled in that state, but the keyboard binding can still fire. */
export function triggerDownload(): void {
  const download = activeDownload();
  if (!download) return;
  void (async () => downloadBlob(download.name, await download.getBlob()))();
}

/** Triggers a browser download of `blob` as `name` via a throwaway anchor +
 *  object URL. */
export function downloadBlob(name: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
