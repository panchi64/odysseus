import { For, Show, type JSX } from "solid-js";
import { EmptyState, LoadingText, Panel, Resource, Stack, toast } from "~/ui";
import {
  downloadModel,
  useEngineSelection,
  useManagedModels,
  useRecommendations,
  type ManagedModelsController,
} from "../serving";
import {
  useManagedModelActions,
  type ManagedModelActions,
} from "../serving-actions";
import type { EngineKind, Workload } from "../model";
import { ManagedModelRow } from "./ManagedModelRow";
import { EnginePicker } from "./EnginePicker";
import { EngineSwitchNote } from "./EngineSwitchNote";
import { RepoDownloadForm } from "./RepoDownloadForm";
import { RepoFinderHint } from "./RepoFinderHint";
import { HfTokenNotice } from "./HfTokenNotice";
import { ModelsDirSection } from "./ModelsDirSection";

/** The LOCAL MODELS tab body: the ranked inference engines for this host, a
 *  free-text Hugging Face repo download (with guidance + an optional HF token step),
 *  and the live managed-models list with serve/stop/delete controls.
 *
 *  Presentation-only: the backend ranks the engines and owns every lifecycle
 *  transition; this surface relays the operator's intent and renders the reported
 *  state. There is no curated model list — the operator points at any HF repo. */
export function LocalModelsPanel(): JSX.Element {
  const recommendations = useRecommendations();
  const managed = useManagedModels();
  const actions = useManagedModelActions(managed);

  // The selected engine (preselected to the host's top pick, self-healing) drives the
  // free-text download below.
  const [selectedEngine, setSelectedEngine] =
    useEngineSelection(recommendations);

  async function startDownload(input: {
    engine: EngineKind;
    repo: string;
    quant?: string;
    workload?: Workload;
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
            <EnginePicker
              recs={recs()}
              selected={selectedEngine()}
              onSelect={setSelectedEngine}
            />
          )}
        </Resource>
      </Panel>

      <Panel label="DOWNLOAD A MODEL">
        <Stack gap={3}>
          <EngineSwitchNote />
          <RepoFinderHint engine={selectedEngine()} workload="chat" />
          <RepoDownloadForm
            engine={selectedEngine()}
            onDownload={(repo, quant) => {
              const engine = selectedEngine();
              if (!engine) return Promise.resolve();
              return startDownload({ engine, repo, quant, workload: "chat" });
            }}
          />
          <HfTokenNotice />
        </Stack>
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
