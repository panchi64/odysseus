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
  Input,
  LoadingText,
  Row,
  Stack,
  Text,
  toast,
} from "~/ui";
import { refreshEndpoints } from "~/lib/stores/models";
import {
  serveModel,
  useEngineSelection,
  useManagedModels,
  useRecommendations,
} from "../serving";
import {
  AdvancedServeOptions,
  EMPTY_OPTIONS,
  hasAnyOption,
} from "./AdvancedServeOptions";
import { DownloadProgress } from "./DownloadProgress";
import { EnginePicker } from "./EnginePicker";
import { EngineSwitchNote } from "./EngineSwitchNote";
import { QuantSelect } from "./QuantSelect";
import { RepoFinderHint } from "./RepoFinderHint";
import { HfTokenNotice } from "./HfTokenNotice";
import { ServeStateFlag } from "./ServeStateFlag";

/** The "RUN LOCALLY" path: the operator picks an inference engine (the recommended one
 *  for this host is preselected, so a one-tap accept is the default), pastes any Hugging
 *  Face repo, and presses DOWNLOAD & SERVE. The model downloads and comes up bound to
 *  `main`, with live progress, then it's ready to chat.
 *
 *  Presentation-only: the backend ranks the engines and owns the download/serve
 *  lifecycle; this form captures the chosen engine + repo and renders the reported state.
 *  `onDone` collapses back to the two-choice entry. */
export function LocalSetupForm(props: { onDone: () => void }): JSX.Element {
  const recommendations = useRecommendations();
  const managed = useManagedModels();

  const [selected, setSelected] = useEngineSelection(recommendations);
  const [repo, setRepo] = createSignal("");
  const [quant, setQuant] = createSignal("");
  const [options, setOptions] = createSignal(EMPTY_OPTIONS);
  const [servedId, setServedId] = createSignal<string | null>(null);
  const [submitting, setSubmitting] = createSignal(false);

  const hasAvailable = () =>
    (recommendations.latest ?? []).some((r) => r.available);

  // The just-served model, tracked through the managed-models poll.
  const served = createMemo(() => {
    const id = servedId();
    return id ? (managed.models().find((m) => m.id === id) ?? null) : null;
  });

  // Once it's running, surface it in the shared endpoint store so it appears in the
  // top-bar picker and Settings immediately.
  createEffect(() => {
    if (served()?.state === "running") refreshEndpoints();
  });

  const canSubmit = () =>
    !submitting() && selected() != null && repo().trim().length > 0;

  async function downloadAndServe(): Promise<void> {
    const engine = selected();
    if (engine == null || !canSubmit()) return;
    setSubmitting(true);
    try {
      const model = await serveModel({
        engine,
        repo: repo().trim(),
        role: "main",
        workload: "chat",
        quant: (engine === "llama.cpp" && quant().trim()) || undefined,
        // Sent only when the advanced section was actually filled in, and only for the
        // engine that has these flags: an untouched section must omit the field so a
        // re-serve keeps the model's existing tuning instead of clearing it, and MLX
        // would store llama.cpp overrides it never applies.
        options:
          engine === "llama.cpp" && hasAnyOption(options())
            ? options()
            : undefined,
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
        when={hasAvailable()}
        fallback={
          <EmptyState
            icon="cpu"
            message="NO LOCAL ENGINE AVAILABLE"
            hint="No inference engine can run on this host yet. Use a remote API instead."
          />
        }
      >
        <Show
          when={servedId()}
          fallback={
            <Stack gap={3}>
              <Stack gap={2}>
                <Text variant="label" tone="dim">
                  CHOOSE AN ENGINE
                </Text>
                <div class="border border-line bg-surface">
                  <EnginePicker
                    recs={recommendations.latest!}
                    selected={selected()}
                    onSelect={setSelected}
                  />
                </div>
              </Stack>
              <EngineSwitchNote />
              <Row gap={3} align="end">
                <div class="min-w-0 flex-1">
                  <Input
                    label="HUGGING FACE REPO"
                    placeholder="org/model"
                    value={repo()}
                    onInput={(e) => setRepo(e.currentTarget.value)}
                  />
                </div>
                <QuantSelect
                  repo={repo()}
                  engine={selected()}
                  value={quant()}
                  onChange={setQuant}
                />
              </Row>
              <HfTokenNotice />
              <AdvancedServeOptions
                engine={selected()}
                value={options()}
                onChange={setOptions}
              />
              <Row gap={3} align="end" justify="between" wrap>
                <div class="min-w-0">
                  <RepoFinderHint engine={selected()} workload="chat" />
                </div>
                <Row gap={2} justify="end" class="shrink-0">
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
                  <Row align="center" gap={2} class="min-w-0">
                    <Text variant="label" tone="dim" class="shrink-0">
                      {m().engine}
                    </Text>
                    <Text variant="label" tone="bright" class="truncate">
                      {m().hfRepo}
                    </Text>
                  </Row>
                  <ServeStateFlag state={m().state} />
                </Row>
                <Show when={m().state === "downloading" && m().progress}>
                  <DownloadProgress progress={m().progress!} />
                </Show>
                <Show when={m().state === "running"}>
                  <Text variant="micro" tone="nominal">
                    Now serving as your main model on {m().engine} — start
                    chatting.
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
      </Show>
    </Show>
  );
}
