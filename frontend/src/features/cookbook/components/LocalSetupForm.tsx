import {
  createEffect,
  createMemo,
  createSignal,
  Show,
  type JSX,
} from "solid-js";
import {
  Button,
  EmptyState,
  LoadingText,
  Row,
  Select,
  Stack,
  Text,
  toast,
} from "~/ui";
import { refreshEndpoints } from "~/lib/stores/models";
import { serveModel, useManagedModels, useRecommendations } from "../serving";
import { DownloadProgress } from "./DownloadProgress";
import { ServeStateFlag } from "./ServeStateFlag";

/** The least-friction "RUN LOCALLY" path: the backend's top available engine is
 *  chosen automatically and its top curated chat model is prefilled, so the
 *  operator only has to press DOWNLOAD & SERVE. The model downloads and comes up
 *  bound to `main`, with live progress, then it's ready to chat.
 *
 *  Presentation-only: the backend picks the engine, curates the models, and owns
 *  the download/serve lifecycle; this form captures the choice and renders the
 *  reported state. `onDone` collapses back to the two-choice entry. */
export function LocalSetupForm(props: { onDone: () => void }): JSX.Element {
  const recommendations = useRecommendations();
  const managed = useManagedModels();

  const [repo, setRepo] = createSignal("");
  const [servedId, setServedId] = createSignal<string | null>(null);
  const [submitting, setSubmitting] = createSignal(false);

  // Serve with the top *available* engine — the same one the LOCAL MODELS tab
  // leads with (the backend already ranked them for this host).
  const engine = createMemo(
    () => recommendations.latest?.find((r) => r.available) ?? null,
  );
  // Its curated chat models, host-ranked by the backend.
  const models = createMemo(() => engine()?.recommendedModels ?? []);

  // Prefill the selection with the top curated model once they load.
  createEffect(() => {
    const list = models();
    if (list.length && !repo()) setRepo(list[0].repo);
  });

  const selected = createMemo(
    () => models().find((m) => m.repo === repo()) ?? null,
  );

  // The just-served model, tracked through the managed-models poll.
  const served = createMemo(() => {
    const id = servedId();
    return id ? (managed.models().find((m) => m.id === id) ?? null) : null;
  });

  // Once it's running, surface it in the shared endpoint store so it appears in
  // the top-bar picker and Settings immediately.
  createEffect(() => {
    if (served()?.state === "running") refreshEndpoints();
  });

  const canSubmit = () =>
    !submitting() && !!engine() && repo().trim().length > 0;

  async function downloadAndServe(): Promise<void> {
    const eng = engine();
    if (!eng || !canSubmit()) return;
    setSubmitting(true);
    try {
      const model = await serveModel({
        engine: eng.engine,
        repo: repo().trim(),
        role: "main",
        workload: "chat",
        quant: selected()?.quant ?? undefined,
      });
      setServedId(model.id);
      toast.success(`Serving ${model.hfRepo} as your main model`);
      managed.refresh();
    } catch (err) {
      toast.error(
        (err as { detail?: string })?.detail ??
          "Unable to start the local model",
      );
    } finally {
      setSubmitting(false);
    }
  }

  const modelOptions = () =>
    models().map((m) => ({ value: m.repo, label: m.label }));

  return (
    <Show
      when={recommendations.latest}
      fallback={
        <div class="p-3">
          <LoadingText label="READING ENGINES" />
        </div>
      }
    >
      <Show
        when={engine()}
        fallback={
          <EmptyState
            icon="cpu"
            message="NO LOCAL ENGINE AVAILABLE"
            hint="No inference engine can run on this host yet. Use a remote API instead."
          />
        }
      >
        {(eng) => (
          <Show
            when={servedId()}
            fallback={
              <Stack gap={3}>
                <Row align="center" justify="between" gap={3}>
                  <Text variant="micro" tone="dim">
                    ENGINE
                  </Text>
                  <Text variant="label" tone="bright">
                    {eng().engine}
                  </Text>
                </Row>
                <Show
                  when={models().length}
                  fallback={
                    <Text variant="micro" tone="dim">
                      No curated models for this engine yet — use the LOCAL
                      MODELS tab to download one by Hugging Face repo.
                    </Text>
                  }
                >
                  <Select
                    label="MODEL"
                    options={modelOptions()}
                    value={repo()}
                    onChange={setRepo}
                  />
                  <Show when={selected()?.notes}>
                    <Text variant="micro" tone="dim">
                      {selected()!.notes}
                    </Text>
                  </Show>
                </Show>
                <Row gap={2} justify="end">
                  <Button
                    variant="ghost"
                    disabled={submitting()}
                    onClick={props.onDone}
                  >
                    CANCEL
                  </Button>
                  <Button
                    variant="primary"
                    leading="download"
                    disabled={!canSubmit()}
                    onClick={downloadAndServe}
                  >
                    {submitting() ? "STARTING…" : "DOWNLOAD & SERVE"}
                  </Button>
                </Row>
              </Stack>
            }
          >
            <Show
              when={served()}
              fallback={
                <div class="p-3">
                  <LoadingText label="STARTING" />
                </div>
              }
            >
              {(m) => (
                <Stack gap={3}>
                  <Row align="center" justify="between" gap={3}>
                    <Text variant="label" tone="bright" class="truncate">
                      {m().hfRepo}
                    </Text>
                    <ServeStateFlag state={m().state} />
                  </Row>
                  <Show when={m().state === "downloading" && m().progress}>
                    <DownloadProgress progress={m().progress!} />
                  </Show>
                  <Show when={m().state === "running"}>
                    <Text variant="micro" tone="nominal">
                      Now serving as your main model — start chatting.
                    </Text>
                  </Show>
                  <Show when={m().state === "error" && m().lastError}>
                    <Text variant="micro" tone="alert">
                      {m().lastError}
                    </Text>
                  </Show>
                  <Row gap={2} justify="end">
                    <Show when={m().state === "error"}>
                      <Button variant="ghost" onClick={() => setServedId(null)}>
                        TRY AGAIN
                      </Button>
                    </Show>
                    <Button
                      variant={m().state === "running" ? "primary" : "ghost"}
                      onClick={props.onDone}
                    >
                      {m().state === "running" ? "DONE" : "BACK"}
                    </Button>
                  </Row>
                </Stack>
              )}
            </Show>
          </Show>
        )}
      </Show>
    </Show>
  );
}
