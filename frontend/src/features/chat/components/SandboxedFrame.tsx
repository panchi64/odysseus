import { createMemo, Show, type JSX } from "solid-js";
import { cx } from "~/ui";

/**
 * The single mount point for model-generated markup — a static HTML version or the
 * live View head. Deliberately sandboxed **without** `allow-same-origin`, so the
 * framed content runs in an opaque origin and can't read the operator's cookies or
 * act as the operator against the API. Keep this the only place the `sandbox` value
 * lives so that security contract can't silently drift between render paths.
 *
 * An iframe loads its `src` once; bumping `reloadKey` (or changing `src`) tears the
 * element down and remounts a fresh one — the same recovery a manual close/reopen
 * gives, so a live preview that loaded before its server was ready can be reloaded.
 */
export function SandboxedFrame(props: {
  src: string;
  title: string;
  class?: string;
  reloadKey?: number;
}): JSX.Element {
  // A keyed Show recreates the iframe only when this string changes — i.e. on a new
  // src or a reload bump — forcing a fresh fetch. The version path omits `reloadKey`,
  // so its key varies only by its stable blob src (no behavior change).
  const mountKey = createMemo(() => `${props.src}#${props.reloadKey ?? 0}`);
  return (
    <Show keyed when={mountKey()}>
      <iframe
        src={props.src}
        title={props.title}
        class={cx("h-full w-full border-0 bg-bright", props.class)}
        sandbox="allow-scripts allow-forms allow-popups"
      />
    </Show>
  );
}
