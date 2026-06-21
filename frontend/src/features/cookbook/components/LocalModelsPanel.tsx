import {
  createEffect,
  createResource,
  createSignal,
  For,
  Show,
  type JSX,
} from "solid-js";
import {
  Button,
  Chip,
  EmptyState,
  Input,
  LoadingText,
  ListRow,
  Panel,
  Resource,
  Row,
  Stack,
  StatusFlag,
  Text,
  toast,
} from "~/ui";
import { bytes } from "~/lib/format";
import {
  downloadModel,
  fetchModelsDir,
  inFlightRepos,
  updateModelsDir,
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

/** A single ranked engine: name, availability flag, reason, and workloads. The
 *  rank-1 engine leads. Read-only — an engine is a serving runtime, not a model,
 *  so there's nothing to serve/stop here (that lives on the managed-model rows). */
function EngineRow(props: { rec: EngineRecommendation }): JSX.Element {
  return (
    <Stack gap={2} class="border-b border-line px-3 py-3 last:border-0">
      <Row align="center" justify="between" gap={3}>
        <Row align="center" gap={2} class="min-w-0">
          <Text variant="label" tone="bright">
            {props.rec.engine}
          </Text>
          <Show when={props.rec.rank === 1}>
            <StatusFlag status="info">RECOMMENDED</StatusFlag>
          </Show>
        </Row>
        <StatusFlag status={props.rec.available ? "nominal" : "idle"} dot>
          {props.rec.available ? "AVAILABLE" : "UNAVAILABLE"}
        </StatusFlag>
      </Row>
      <Text variant="micro" tone="dim">
        {props.rec.reason}
      </Text>
      <Show when={props.rec.available}>
        <Text variant="micro" tone="dim">
          {props.rec.installed
            ? "Ready — engine runtime is installed."
            : "Downloads engine (~once) on first serve."}
        </Text>
      </Show>
      <Show when={props.rec.workloads.length}>
        <Row gap={2} align="center" class="flex-wrap">
          <For each={props.rec.workloads}>
            {(w) => <Chip>{w.toUpperCase()}</Chip>}
          </For>
        </Row>
      </Show>
    </Stack>
  );
}

/** One curated catalog model — label + params/quant/size meta, a TOOLS flag when
 *  it supports native tool-calling, and a DOWNLOAD action. Download is disabled
 *  while this repo already has an in-flight managed model. */
function CatalogRow(props: {
  entry: CatalogEntry;
  inFlight: boolean;
  onDownload: () => void;
}): JSX.Element {
  return (
    <ListRow
      label={props.entry.label}
      leading="cpu"
      right={
        <Row gap={2} align="center">
          <Show when={props.entry.params}>
            <Text variant="micro" tone="dim">
              {props.entry.params}
            </Text>
          </Show>
          <Show when={props.entry.quant}>
            <Text variant="micro" tone="dim">
              {props.entry.quant}
            </Text>
          </Show>
          <Show when={props.entry.approxBytes != null}>
            <Text variant="micro" tone="dim">
              {bytes(props.entry.approxBytes!)}
            </Text>
          </Show>
          <Show when={props.entry.nativeTools}>
            <StatusFlag status="nominal">TOOLS</StatusFlag>
          </Show>
          <Button
            size="sm"
            leading="download"
            disabled={props.inFlight}
            onClick={props.onDownload}
          >
            {props.inFlight ? "DOWNLOADING" : "DOWNLOAD"}
          </Button>
        </Row>
      }
    />
  );
}

/** The free-text "download by HF repo" row: a repo id + optional quant, run on
 *  the top available engine with its default `chat` workload. Validation is
 *  UX-only — the backend is the authority. */
function RepoDownloadForm(props: {
  engine: EngineKind | null;
  onDownload: (repo: string, quant: string | undefined) => Promise<void>;
}): JSX.Element {
  const [repo, setRepo] = createSignal("");
  const [quant, setQuant] = createSignal("");
  const [busy, setBusy] = createSignal(false);
  const canSubmit = () => repo().trim().length > 0 && !busy() && !!props.engine;

  async function submit(e: Event): Promise<void> {
    e.preventDefault();
    if (!canSubmit()) return;
    setBusy(true);
    try {
      await props.onDownload(repo().trim(), quant().trim() || undefined);
      setRepo("");
      setQuant("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <Row gap={3} align="end" class="flex-wrap">
        <div class="min-w-0 flex-1">
          <Input
            label="HUGGING FACE REPO"
            placeholder="org/model"
            value={repo()}
            onInput={(e) => setRepo(e.currentTarget.value)}
          />
        </div>
        <div class="w-32">
          <Input
            label="QUANT (OPTIONAL)"
            placeholder="Q4_K_M"
            value={quant()}
            onInput={(e) => setQuant(e.currentTarget.value)}
          />
        </div>
        <Button type="submit" leading="download" disabled={!canSubmit()}>
          {busy() ? "DOWNLOADING" : "DOWNLOAD"}
        </Button>
      </Row>
      <Show when={!props.engine}>
        <Text variant="micro" tone="dim" class="mt-1">
          No available engine to download with on this host yet.
        </Text>
      </Show>
    </form>
  );
}

/** Where new model downloads are written. Loads the current dir and lets the
 *  operator point it elsewhere. Validation is the backend's job — it returns 400
 *  with a reason — so the only client-side gate is non-empty; the displayed value
 *  refreshes from the stored absolute path the backend returns. */
function ModelsDirSection(): JSX.Element {
  const [dir, { mutate, refetch }] = createResource(fetchModelsDir);
  const [value, setValue] = createSignal("");
  const [saving, setSaving] = createSignal(false);

  // Prefill the field once the current dir loads (and on a successful save).
  createEffect(() => {
    const current = dir.latest;
    if (current != null) setValue(current);
  });

  const canSave = () => value().trim().length > 0 && !saving();

  async function save(): Promise<void> {
    if (!canSave()) return;
    setSaving(true);
    try {
      const stored = await updateModelsDir(value().trim());
      mutate(stored);
      setValue(stored);
      toast.success("Models directory updated");
    } catch (err) {
      toast.error(
        (err as { detail?: string })?.detail ??
          "Couldn't update the models directory",
      );
      void refetch();
    } finally {
      setSaving(false);
    }
  }

  return (
    <Panel label="MODELS DIRECTORY">
      <Stack gap={3}>
        <Row gap={3} align="end" class="flex-wrap">
          <div class="min-w-0 flex-1">
            <Input
              label="DIRECTORY"
              placeholder="/path/to/models"
              value={value()}
              onInput={(e) => setValue(e.currentTarget.value)}
              disabled={dir.loading}
            />
          </div>
          <Button leading="check" disabled={!canSave()} onClick={save}>
            {saving() ? "SAVING…" : "SAVE"}
          </Button>
        </Row>
        <Text variant="micro" tone="dim">
          Applies to new downloads — existing models stay where they are.
        </Text>
      </Stack>
    </Panel>
  );
}

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
                  inFlight={inFlight().has(entry.repo)}
                  onDownload={() =>
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
