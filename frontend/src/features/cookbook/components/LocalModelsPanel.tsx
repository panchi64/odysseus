import { For, Show, type JSX } from "solid-js";
import { EmptyState, LoadingText, Panel, Resource, Stack, toast } from "~/ui";
import {
  downloadModel,
  supportedOptionsFor,
  useEngineSelection,
  useManagedModels,
  usePathPicker,
  useRecommendations,
  type ManagedModelsController,
} from "../serving";
import {
  useManagedModelActions,
  type ManagedModelActions,
} from "../serving-actions";
import type { EngineKind, Workload } from "~/lib/api/models-types";
import type { EngineRecommendation } from "../model";
import { ManagedModelRow } from "./ManagedModelRow";
import { EnginePicker } from "./EnginePicker";
import { EngineSwitchNote } from "./EngineSwitchNote";
import { LocalArtifactForm } from "./LocalArtifactForm";
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
  const picker = usePathPicker();

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
      <Panel label="Inference engines" flush>
        <Resource
          data={recommendations}
          loadingLabel="Reading engines"
          errorMessage="Failed to read engines"
          isEmpty={(v) => v.length === 0}
          loading={
            <div class="p-3">
              <LoadingText />
            </div>
          }
          empty={
            <EmptyState
              icon="cpu"
              message="No engines detected"
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

      <Panel label="Download a model">
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

      <Panel label="Use a model on disk">
        <LocalArtifactForm
          engine={selectedEngine()}
          picker={picker()}
          onImported={() => managed.refresh()}
        />
      </Panel>

      <ModelsDirSection />

      <ManagedModelsPanel
        controller={managed}
        actions={actions}
        recommendations={recommendations.latest}
      />
    </Stack>
  );
}

/** The MANAGED MODELS list, driven by the polling controller — one row per model
 *  with its state, live progress while downloading, the named step while starting,
 *  per-model tuning, and lifecycle actions. Empty until the first model is added.
 *
 *  This panel names no role on serve. The backend claims the chat role itself when
 *  nothing else usable is bound, and each running row offers USE FOR CHAT for the case
 *  where more than one model is live and the choice is genuinely the operator's. */
function ManagedModelsPanel(props: {
  controller: ManagedModelsController;
  actions: ManagedModelActions;
  recommendations: EngineRecommendation[] | undefined;
}): JSX.Element {
  return (
    <Panel label="Managed models" flush>
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
              message="No managed models"
              hint="Download a model above to start managing it here."
            />
          }
        >
          <Stack gap={0}>
            <For each={props.controller.models()}>
              {(model) => (
                <ManagedModelRow
                  model={model}
                  supportedOptions={supportedOptionsFor(
                    props.recommendations,
                    model.engine,
                  )}
                  onServe={(options) =>
                    props.actions.serve({
                      engine: model.engine,
                      repo: model.hfRepo,
                      quant: model.quant ?? undefined,
                      workload: model.workload,
                      options,
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
