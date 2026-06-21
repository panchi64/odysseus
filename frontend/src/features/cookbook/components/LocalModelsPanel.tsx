import { For, Show, type JSX } from "solid-js";
import {
  EmptyState,
  LoadingText,
  Panel,
  Resource,
  Stack,
  Text,
  toast,
} from "~/ui";
import {
  downloadModel,
  inFlightRepos,
  useManagedModels,
  useRecommendations,
  type ManagedModelsController,
} from "../serving";
import {
  useManagedModelActions,
  type ManagedModelActions,
} from "../serving-actions";
import type { CatalogEntry, EngineKind, EngineRecommendation } from "../model";
import { ManagedModelRow } from "./ManagedModelRow";
import { EngineRow } from "./EngineRow";
import { CatalogRow } from "./CatalogRow";
import { RepoDownloadForm } from "./RepoDownloadForm";
import { ModelsDirSection } from "./ModelsDirSection";

/** The LOCAL MODELS tab body: the ranked inference engines for this host, the
 *  curated model catalog from the top available engine (each row downloadable),
 *  a free-text repo download, and the live managed-models list with serve/stop/
 *  delete controls.
 *
 *  Presentation-only: the backend ranks the engines, curates the catalog, and
 *  owns every lifecycle transition; this surface relays the operator's intent and
 *  renders the backend's reported state. */
export function LocalModelsPanel(): JSX.Element {
  const recommendations = useRecommendations();
  const managed = useManagedModels();
  const actions = useManagedModelActions(managed);

  // Lead with the rank-1 engine; the curated catalog comes from the top
  // *available* engine's recommended models (the backend already ranked them).
  const topAvailable = (recs: EngineRecommendation[]) =>
    recs.find((r) => r.available) ?? recs[0];

  // The engine the free-text download targets — the top available one.
  const downloadEngine = (): EngineKind | null => {
    const recs = recommendations.latest;
    if (!recs) return null;
    return recs.find((r) => r.available)?.engine ?? null;
  };

  // The repos with an in-flight download/start — used to disable a catalog
  // DOWNLOAD button so it can't double-fire.
  const inFlight = () => inFlightRepos(managed.models());

  async function startDownload(input: {
    engine: EngineKind;
    repo: string;
    quant?: string;
    workload?: CatalogEntry["workload"];
  }): Promise<void> {
    try {
      await downloadModel(input);
      toast.success(`Downloading ${input.repo}`);
      managed.refresh();
    } catch (err) {
      toast.error(
        (err as { detail?: string })?.detail ??
          `Unable to download ${input.repo}`,
      );
    }
  }

  return (
    <Stack gap={6}>
      <Panel label="INFERENCE ENGINES" flush>
        <Resource
          data={recommendations}
          loadingLabel="READING ENGINES"
          errorMessage="FAILED TO READ ENGINES"
          isEmpty={(v) => v.length === 0}
          loading={
            <div class="p-3">
              <LoadingText />
            </div>
          }
          empty={
            <EmptyState
              icon="cpu"
              message="NO ENGINES DETECTED"
              hint="No local inference engine is available on this host yet."
            />
          }
        >
          {(recs) => (
            <Stack gap={0}>
              <For each={[...recs()].sort((a, b) => a.rank - b.rank)}>
                {(rec) => <EngineRow rec={rec} />}
              </For>
            </Stack>
          )}
        </Resource>
      </Panel>

      <Panel
        label="CURATED CATALOG"
        meta={
          <Text variant="micro" tone="dim">
            MODELS THIS HOST CAN RUN
          </Text>
        }
        flush
      >
        <Resource
          data={recommendations}
          loadingLabel="LOADING CATALOG"
          errorMessage="FAILED TO LOAD CATALOG"
          isEmpty={(v) => topAvailable(v)?.recommendedModels.length === 0}
          loading={
            <div class="p-3">
              <LoadingText />
            </div>
          }
          empty={
            <EmptyState
              icon="database"
              message="NO CURATED MODELS"
              hint="No models are curated for the available engine yet."
            />
          }
        >
          {(recs) => (
            <For each={topAvailable(recs())?.recommendedModels ?? []}>
              {(entry) => (
                <CatalogRow
                  entry={entry}
                  leading="cpu"
                  actionIcon="download"
                  actionLabel="DOWNLOAD"
                  busyLabel="DOWNLOADING"
                  inFlight={inFlight().has(entry.repo)}
                  onAction={() =>
                    void startDownload({
                      engine: entry.engine,
                      repo: entry.repo,
                      quant: entry.quant ?? undefined,
                      workload: entry.workload,
                    })
                  }
                />
              )}
            </For>
          )}
        </Resource>
      </Panel>

      <Panel label="DOWNLOAD BY HUGGING FACE REPO">
        <RepoDownloadForm
          engine={downloadEngine()}
          onDownload={(repo, quant) => {
            const engine = downloadEngine();
            if (!engine) return Promise.resolve();
            return startDownload({ engine, repo, quant, workload: "chat" });
          }}
        />
      </Panel>

      <ModelsDirSection />

      <ManagedModelsPanel controller={managed} actions={actions} />
    </Stack>
  );
}

/** The MANAGED MODELS list, driven by the polling controller — one row per model
 *  with its state, (while downloading) live progress, and lifecycle actions.
 *  Empty until the first download lands. A re-served model keeps whatever role it
 *  carried before it was stopped (this panel binds none — the headline GET STARTED
 *  flow owns role binding). */
function ManagedModelsPanel(props: {
  controller: ManagedModelsController;
  actions: ManagedModelActions;
}): JSX.Element {
  return (
    <Panel label="MANAGED MODELS" flush>
      <Show
        when={!props.controller.loading() || props.controller.models().length}
        fallback={
          <div class="p-3">
            <LoadingText />
          </div>
        }
      >
        <Show
          when={props.controller.models().length}
          fallback={
            <EmptyState
              icon="database"
              message="NO MANAGED MODELS"
              hint="Download a model above to start managing it here."
            />
          }
        >
          <Stack gap={0}>
            <For each={props.controller.models()}>
              {(model) => (
                <ManagedModelRow
                  model={model}
                  onServe={() =>
                    props.actions.serve({
                      engine: model.engine,
                      repo: model.hfRepo,
                      quant: model.quant ?? undefined,
                      workload: model.workload,
                    })
                  }
                  onStop={() => props.actions.stop(model)}
                  onDelete={() => props.actions.remove(model)}
                />
              )}
            </For>
          </Stack>
        </Show>
      </Show>
    </Panel>
  );
}
