/** Renders an audio or video artifact via the native `<audio>`/`<video>` element —
 *  no bespoke player chrome, just the browser's own controls. The kind is inferred
 *  from the filename extension (`detectContentKind`); the blob is played from an
 *  object URL, revoked on cleanup/replacement. */

import {
  createEffect,
  createMemo,
  createSignal,
  onCleanup,
  Show,
  type JSX,
} from "solid-js";
import { detectContentKind } from "../../viewport";

export function MediaPlayer(props: {
  data: Blob;
  name: string;
  fontStep?: number;
  softWrap?: boolean;
  scrollKey?: string;
}): JSX.Element {
  const [url, setUrl] = createSignal<string | null>(null);

  createEffect(() => {
    const objectUrl = URL.createObjectURL(props.data);
    setUrl(objectUrl);
    onCleanup(() => URL.revokeObjectURL(objectUrl));
  });

  const kind = createMemo(() => detectContentKind(props.name, null));

  return (
    <div class="flex h-full min-h-0 items-center justify-center p-4">
      <Show when={url()}>
        {(u) => (
          <Show
            when={kind() === "video"}
            fallback={<audio class="w-full max-w-md" controls src={u()} />}
          >
            <video
              class="h-full max-h-full w-full max-w-full object-contain"
              controls
              src={u()}
            />
          </Show>
        )}
      </Show>
    </div>
  );
}
