import { createResource, onCleanup, Show, Suspense, type JSX } from "solid-js";
import { api } from "~/lib/api";
import { ErrorState, LoadingText, Panel, Row, Text } from "~/ui";
import type { ArtifactRef } from "../model";

type Loaded = { mode: "text"; text: string } | { mode: "url"; url: string };

/**
 * Renders a published artifact in-thread. The bytes are auth-gated, so we fetch
 * them with the client and hand the iframe/img a blob URL (an `<img src>` can't
 * carry a bearer). HTML renders in an opaque-origin sandboxed iframe — no
 * `allow-same-origin`, so model-generated markup can't act as the operator.
 */
export function ArtifactViewer(props: { artifact: ArtifactRef }): JSX.Element {
  let objectUrl: string | null = null;

  const [loaded] = createResource(
    () => props.artifact.artifactId,
    async (id): Promise<Loaded> => {
      const blob = await api.getBlob(`/artifacts/${id}/content`);
      if (props.artifact.kind === "text") {
        return { mode: "text", text: await blob.text() };
      }
      objectUrl = URL.createObjectURL(blob);
      return { mode: "url", url: objectUrl };
    },
  );

  onCleanup(() => {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  });

  return (
    <Panel
      label={`ARTIFACT · ${props.artifact.kind.toUpperCase()}`}
      meta={
        <Text variant="micro" tone="dim">
          {props.artifact.filename}
        </Text>
      }
    >
      <Suspense fallback={<LoadingText label="LOADING ARTIFACT…" />}>
        <Show
          when={loaded()}
          fallback={<ErrorState message="Could not load the artifact." />}
        >
          {(data) => (
            <>
              <Show
                when={data().mode === "url" && props.artifact.kind === "image"}
              >
                <img
                  src={(data() as { url: string }).url}
                  alt={props.artifact.title}
                  class="max-h-96 max-w-full"
                />
              </Show>
              <Show
                when={data().mode === "url" && props.artifact.kind === "html"}
              >
                <iframe
                  src={(data() as { url: string }).url}
                  title={props.artifact.title}
                  class="h-96 w-full border-0 bg-bright"
                  sandbox="allow-scripts allow-forms allow-popups"
                />
              </Show>
              <Show when={data().mode === "text"}>
                <pre class="max-h-96 overflow-auto whitespace-pre-wrap break-words font-mono text-body text-text">
                  {(data() as { text: string }).text}
                </pre>
              </Show>
              <Show when={props.artifact.kind === "other"}>
                <Row gap={2} align="center">
                  <Text variant="micro" tone="dim">
                    {props.artifact.contentType} — preview not supported.
                  </Text>
                </Row>
              </Show>
            </>
          )}
        </Show>
      </Suspense>
    </Panel>
  );
}
