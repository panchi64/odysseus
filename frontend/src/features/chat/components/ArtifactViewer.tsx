import { createResource, Match, Show, Switch, type JSX } from "solid-js";
import { api, useAuthedBlobUrl } from "~/lib/api";
import { ErrorState, LoadingText, Panel, Row, Text } from "~/ui";
import type { ArtifactRef } from "../model";

/**
 * Renders a published artifact in-thread. The bytes are auth-gated, so image and
 * HTML kinds resolve through the shared blob-URL hook (an `<img>` / iframe `src`
 * can't carry a bearer); text is read inline. HTML renders in an opaque-origin
 * sandboxed iframe — no `allow-same-origin`, so model-generated markup can't act
 * as the operator.
 */
export function ArtifactViewer(props: { artifact: ArtifactRef }): JSX.Element {
  const contentPath = (): string =>
    `/artifacts/${props.artifact.artifactId}/content`;
  const isUrlKind = (): boolean =>
    props.artifact.kind === "image" || props.artifact.kind === "html";

  const objectUrl = useAuthedBlobUrl(() =>
    isUrlKind() ? contentPath() : undefined,
  );
  const [text] = createResource(
    () =>
      props.artifact.kind === "text" ? props.artifact.artifactId : undefined,
    async (): Promise<string> => (await api.getBlob(contentPath())).text(),
  );

  const urlArm = (render: (url: string) => JSX.Element): JSX.Element => (
    <Switch fallback={<LoadingText label="LOADING ARTIFACT…" />}>
      <Match when={objectUrl.error}>
        <ErrorState message="Could not load the artifact." />
      </Match>
      <Match when={objectUrl()}>{(url) => render(url())}</Match>
    </Switch>
  );

  return (
    <Panel
      label={`ARTIFACT · ${props.artifact.kind.toUpperCase()}`}
      meta={
        <Text variant="micro" tone="dim">
          {props.artifact.filename}
        </Text>
      }
    >
      <Show when={props.artifact.kind === "image"}>
        {urlArm((url) => (
          <img
            src={url}
            alt={props.artifact.title}
            class="max-h-96 max-w-full"
          />
        ))}
      </Show>
      <Show when={props.artifact.kind === "html"}>
        {urlArm((url) => (
          <iframe
            src={url}
            title={props.artifact.title}
            class="h-96 w-full border-0 bg-bright"
            sandbox="allow-scripts allow-forms allow-popups"
          />
        ))}
      </Show>
      <Show when={props.artifact.kind === "text"}>
        <Switch fallback={<LoadingText label="LOADING ARTIFACT…" />}>
          <Match when={text.error}>
            <ErrorState message="Could not load the artifact." />
          </Match>
          <Match when={text() !== undefined}>
            <pre class="max-h-96 overflow-auto whitespace-pre-wrap break-words font-mono text-body text-text">
              {text()}
            </pre>
          </Match>
        </Switch>
      </Show>
      <Show when={props.artifact.kind === "other"}>
        <Row gap={2} align="center">
          <Text variant="micro" tone="dim">
            {props.artifact.contentType} — preview not supported.
          </Text>
        </Row>
      </Show>
    </Panel>
  );
}
