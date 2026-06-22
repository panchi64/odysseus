import { For, Show, type JSX } from "solid-js";
import { Panel, Stack, Text } from "~/ui";
import { useManagedModels } from "../serving";
import { useManagedModelActions } from "../serving-actions";
import { ManagedModelRow } from "./ManagedModelRow";
import { RepoDownloadForm } from "./RepoDownloadForm";
import { RepoFinderHint } from "./RepoFinderHint";
import { HfTokenNotice } from "./HfTokenNotice";

/** The EMBEDDING tab's "serve locally" affordance: paste any GGUF embedding repo →
 *  DOWNLOAD & SERVE it via llama.cpp bound to the `embedding` role, which re-indexes the
 *  knowledge base into the new vector space. Embeddings come from llama.cpp on every
 *  platform (one uniform stack), so the engine is fixed.
 *
 *  Presentation-only: the backend owns the download / serve / reindex; this panel relays
 *  intent and renders the reported state. No curated list — the operator points at any
 *  GGUF embedding repo. */
export function EmbeddingServePanel(): JSX.Element {
  const managed = useManagedModels();
  const actions = useManagedModelActions(managed);

  // The embedding-workload managed models (the LOCAL MODELS tab manages chat ones).
  const embeddingModels = () =>
    managed.models().filter((m) => m.workload === "embedding");

  function serveEmbedding(
    repo: string,
    quant: string | undefined,
  ): Promise<void> {
    return actions.serve({
      engine: "llama.cpp",
      repo,
      role: "embedding",
      workload: "embedding",
      quant,
    });
  }

  return (
    <Stack gap={6}>
      <Panel label="SERVE EMBEDDINGS LOCALLY">
        <Stack gap={3}>
          <Text variant="micro" tone="dim">
            Run an embedding model on this machine with llama.cpp and bind it to
            the embedding role. The knowledge base re-indexes into the new
            model's vector space automatically — recall is degraded until it
            finishes.
          </Text>
          <RepoFinderHint engine="llama.cpp" workload="embedding" />
          <RepoDownloadForm
            engine="llama.cpp"
            submitLabel="DOWNLOAD & SERVE"
            busyLabel="SERVING"
            onDownload={serveEmbedding}
          />
          <HfTokenNotice />
        </Stack>
      </Panel>

      <Show when={embeddingModels().length}>
        <Panel label="SERVED EMBEDDING MODELS" flush>
          <Stack gap={0}>
            <For each={embeddingModels()}>
              {(model) => (
                <ManagedModelRow
                  model={model}
                  onServe={() =>
                    actions.serve({
                      engine: model.engine,
                      repo: model.hfRepo,
                      role: "embedding",
                      workload: "embedding",
                      quant: model.quant ?? undefined,
                    })
                  }
                  onStop={() => actions.stop(model)}
                  onDelete={() => actions.remove(model)}
                />
              )}
            </For>
          </Stack>
        </Panel>
      </Show>
    </Stack>
  );
}
