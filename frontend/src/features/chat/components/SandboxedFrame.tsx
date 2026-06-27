import { type JSX } from "solid-js";
import { cx } from "~/ui";

/**
 * The single mount point for model-generated markup — a static HTML version or the
 * live View head. Deliberately sandboxed **without** `allow-same-origin`, so the
 * framed content runs in an opaque origin and can't read the operator's cookies or
 * act as the operator against the API. Keep this the only place the `sandbox` value
 * lives so that security contract can't silently drift between render paths.
 *
 * A `src` change reloads the frame natively (a new live URL, a switched version). A
 * manual reload of the *same* src is driven by remounting this component from the
 * viewport (it keys the content on a refresh nonce), so this stays a thin frame.
 */
export function SandboxedFrame(props: {
  src: string;
  title: string;
  class?: string;
}): JSX.Element {
  return (
    <iframe
      src={props.src}
      title={props.title}
      class={cx("h-full w-full border-0 bg-bright", props.class)}
      sandbox="allow-scripts allow-forms allow-popups"
    />
  );
}
