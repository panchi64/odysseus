import { createResource, For, Show, type JSX } from "solid-js";
import {
  Button,
  EmptyState,
  ListRow,
  LoadingText,
  Panel,
  Resource,
  Row,
  Stack,
  Text,
} from "~/ui";
import { bytes } from "~/lib/format";
import { fetchCatalog, useManagedModels } from "../serving";
import { useManagedModelActions } from "../serving-actions";
import type { CatalogEntry } from "../model";
import { ManagedModelRow } from "./ManagedModelRow";

/** The EMBEDDING tab's "serve locally" affordance: pick a curated GGUF embedding
 *  model → DOWNLOAD & SERVE it via llama.cpp bound to the `embedding` role, which
 *  re-indexes the knowledge base into the new vector space. Embeddings come from
 *  llama.cpp on every platform (one uniform stack), so the engine is fixed.
 *
 *  Presentation-only: the backend curates the catalog and owns the download / serve /
 *  reindex; this panel relays intent and renders the reported state. */
export function EmbeddingServePanel(): JSX.Element {
  const managed = useManagedModels();
  const actions = useManagedModelActions(managed);
  const [catalog] = createResource(() =>
    fetchCatalog("llama.cpp", "embedding"),
  );

  // The embedding-workload managed models (the LOCAL MODELS tab manages chat ones).
  const embeddingModels = () =>
    managed.models().filter((m) => m.workload === "embedding");

  // A repo is "in flight" while it already has a downloading/starting managed model —
  // used to disable its DOWNLOAD & SERVE button so it can't double-fire.
  const inFlightRepos = () =>
    new Set(
      embeddingModels()
        .filter((m) => m.state === "downloading" || m.state === "starting")
        .map((m) => m.hfRepo),
    );

  function serveEmbedding(entry: CatalogEntry): Promise<void> {
    return actions.serve({
      engine: "llama.cpp",
      repo: entry.repo,
      role: "embedding",
      workload: "embedding",
      quant: entry.quant ?? undefined,
    });
  }

  return (
    <Stack gap={6}>
      <Panel label="SERVE EMBEDDINGS LOCALLY">
        <Text variant="micro" tone="dim">
          Run an embedding model on this machine with llama.cpp and bind it to
          the embedding role. The knowledge base re-indexes into the new model's
          vector space automatically — recall is degraded until it finishes.
        </Text>
      </Panel>

      <Panel
        label="EMBEDDING MODELS"
        meta={
          <Text variant="micro" tone="dim">
            MODELS THIS HOST CAN RUN
          </Text>
        }
        flush
      >
        <Resource
          data={catalog}
          loadingLabel="LOADING CATALOG"
          errorMessage="FAILED TO LOAD CATALOG"
          isEmpty={(v) => v.length === 0}
          loading={
            <div class="p-3">
              <LoadingText />
            </div>
          }
          empty={
            <EmptyState
              icon="database"
              message="NO EMBEDDING MODELS"
              hint="No embedding models are curated for this host yet."
            />
          }
        >
          {(entries) => (
            <For each={entries()}>
              {(entry) => (
                <ListRow
                  label={entry.label}
                  leading="database"
                  right={
                    <Row gap={2} align="center">
                      <Show when={entry.params}>
                        <Text variant="micro" tone="dim">
                          {entry.params}
                        </Text>
                      </Show>
                      <Show when={entry.approxBytes != null}>
                        <Text variant="micro" tone="dim">
                          {bytes(entry.approxBytes!)}
                        </Text>
                      </Show>
                      <Button
                        size="sm"
                        leading="play"
                        disabled={inFlightRepos().has(entry.repo)}
                        onClick={() => void serveEmbedding(entry)}
                      >
                        {inFlightRepos().has(entry.repo)
                          ? "SERVING"
                          : "DOWNLOAD & SERVE"}
                      </Button>
                    </Row>
                  }
                />
              )}
            </For>
          )}
        </Resource>
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
