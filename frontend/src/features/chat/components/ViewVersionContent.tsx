import { createResource, Match, Switch, type JSX } from "solid-js";
import { api, useAuthedBlobUrl } from "~/lib/api";
import { ErrorState, LoadingText, Text } from "~/ui";
import type { ViewPreviewRef } from "../model";
import { SandboxedFrame } from "./SandboxedFrame";

/**
 * Renders a version's static **preview** — the captured file a `show(file=…)` stamped on
 * it — by kind: image, HTML, or text (CODE is the version's workspace tree, shown by
 * `ViewSnapshotCode`, so this component only ever renders the preview). The bytes are
 * auth-gated, so image and HTML resolve through the shared blob-URL hook (an `<img>` /
 * iframe `src` can't carry a bearer); text is read inline. HTML renders in an
 * opaque-origin sandboxed iframe — no `allow-same-origin`, so model-generated markup
 * can't act as the operator.
 */
export function ViewVersionContent(props: {
  preview: ViewPreviewRef;
  title: string;
}): JSX.Element {
  const contentPath = (): string =>
    `/views/${props.preview.artifactId}/content`;

  // image + HTML render through the blob-URL hook (their src can't carry a bearer).
  const isUrlKind = (): boolean =>
    props.preview.kind === "image" || props.preview.kind === "html";
  const objectUrl = useAuthedBlobUrl(() =>
    isUrlKind() ? contentPath() : undefined,
  );

  // text renders inline, read through the auth-gated blob fetch.
  const [text] = createResource(
    () =>
      props.preview.kind === "text" ? props.preview.artifactId : undefined,
    async (): Promise<string> => (await api.getBlob(contentPath())).text(),
  );

  const urlArm = (render: (url: string) => JSX.Element): JSX.Element => (
    <Switch fallback={<LoadingText label="LOADING VIEW…" />}>
      <Match when={objectUrl.error}>
        <ErrorState message="Could not load this version." />
      </Match>
      <Match when={objectUrl()}>{(url) => render(url())}</Match>
    </Switch>
  );

  return (
    <Switch>
      <Match when={props.preview.kind === "image"}>
        {urlArm((url) => (
          <img
            src={url}
            alt={props.title}
            class="h-full w-full object-contain"
          />
        ))}
      </Match>
      <Match when={props.preview.kind === "html"}>
        {urlArm((url) => (
          <SandboxedFrame src={url} title={props.title} />
        ))}
      </Match>
      <Match when={props.preview.kind === "text"}>
        <Switch fallback={<LoadingText label="LOADING VIEW…" />}>
          <Match when={text.error}>
            <ErrorState message="Could not load this version." />
          </Match>
          <Match when={text() !== undefined}>
            <pre class="h-full overflow-auto whitespace-pre-wrap break-words p-3 font-mono text-body text-text">
              {text()}
            </pre>
          </Match>
        </Switch>
      </Match>
      <Match when={props.preview.kind === "other"}>
        <div class="flex h-full items-center justify-center p-4">
          <Text variant="micro" tone="dim">
            No inline render for this file.
          </Text>
        </div>
      </Match>
    </Switch>
  );
}
