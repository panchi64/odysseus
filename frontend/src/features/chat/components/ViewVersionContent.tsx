import { createResource, Match, Switch, type JSX } from "solid-js";
import { api, useAuthedBlobUrl } from "~/lib/api";
import { ErrorState, LoadingText, Text } from "~/ui";
import type { ViewVersionRef } from "../model";
import { SandboxedFrame } from "./SandboxedFrame";

/**
 * Renders a static View version's bytes, filling its container. The bytes are
 * auth-gated, so image and HTML resolve through the shared blob-URL hook (an
 * `<img>` / iframe `src` can't carry a bearer); text is read inline. HTML renders
 * in an opaque-origin sandboxed iframe — no `allow-same-origin`, so model-generated
 * markup can't act as the operator.
 */
export function ViewVersionContent(props: {
  version: ViewVersionRef;
}): JSX.Element {
  const contentPath = (): string => `/views/${props.version.versionId}/content`;
  const isUrlKind = (): boolean =>
    props.version.kind === "image" || props.version.kind === "html";

  const objectUrl = useAuthedBlobUrl(() =>
    isUrlKind() ? contentPath() : undefined,
  );
  const [text] = createResource(
    () => (props.version.kind === "text" ? props.version.versionId : undefined),
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
      <Match when={props.version.kind === "image"}>
        {urlArm((url) => (
          <img
            src={url}
            alt={props.version.title}
            class="h-full w-full object-contain"
          />
        ))}
      </Match>
      <Match when={props.version.kind === "html"}>
        {urlArm((url) => (
          <SandboxedFrame src={url} title={props.version.title} />
        ))}
      </Match>
      <Match when={props.version.kind === "text"}>
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
      <Match when={props.version.kind === "other"}>
        <div class="flex h-full items-center justify-center p-4">
          <Text variant="micro" tone="dim">
            {props.version.contentType} — no inline render.
          </Text>
        </div>
      </Match>
    </Switch>
  );
}
