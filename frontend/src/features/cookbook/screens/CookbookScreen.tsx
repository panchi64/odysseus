import { createSignal, Show, Suspense, type JSX } from "solid-js";
import {
  InstrumentBand,
  LoadingText,
  PageHeader,
  Stack,
  StatusFlag,
  Tabs,
} from "~/ui";
import { useHardware } from "../data";
import { EmbeddingPanel } from "../components/EmbeddingPanel";
import { EmbeddingServePanel } from "../components/EmbeddingServePanel";
import { ComparePanel } from "../components/ComparePanel";
import { GetStartedPanel } from "../components/GetStartedPanel";
import { LocalModelsPanel } from "../components/LocalModelsPanel";

export function CookbookScreen(): JSX.Element {
  const hardware = useHardware();
  // Get Started is the front door — the guided "connect a model" flow is the
  // default tab so a fresh operator lands on it.
  const [tab, setTab] = createSignal("getstarted");

  return (
    <Stack gap={6}>
      <PageHeader
        title="MODEL COOKBOOK"
        subtitle="Local and remote model serving, hardware fit, embedding configuration, and side-by-side comparison."
        assetId="SYS-MDL-03.1"
        actions={
          <Show when={hardware.latest}>
            {(hw) => (
              <StatusFlag status="nominal" dot>
                {hw().backend}
              </StatusFlag>
            )}
          </Show>
        }
      />

      <Show when={tab() === "local"}>
        <Suspense fallback={<LoadingText label="READING HARDWARE" />}>
          <Show when={hardware()}>
            {(hw) => (
              <InstrumentBand
                items={[
                  { label: "CHIP", value: hw().chip },
                  { label: "RAM", value: hw().ram },
                  { label: "VRAM", value: hw().vram },
                  { label: "CORES", value: hw().cores },
                  { label: "BACKEND", value: hw().backend },
                  ...(hw().runtimes.length
                    ? hw().runtimes.map((r) => ({
                        label: r.name.toUpperCase(),
                        value: r.version ?? "—",
                      }))
                    : [
                        {
                          label: "RUNTIME",
                          value: "none detected",
                          tone: "dim" as const,
                        },
                      ]),
                ]}
              />
            )}
          </Show>
        </Suspense>
      </Show>

      <Tabs
        items={[
          { value: "getstarted", label: "GET STARTED" },
          { value: "local", label: "LOCAL MODELS" },
          { value: "embedding", label: "EMBEDDING" },
          { value: "compare", label: "COMPARE" },
        ]}
        value={tab()}
        onChange={setTab}
      />

      {/* LOCAL MODELS shows the live hardware readout (above) plus the recommended
          inference engines, the curated catalog for this host, and the managed
          models with download / serve / stop / delete controls. */}
      <Show when={tab() === "local"}>
        <LocalModelsPanel />
      </Show>

      <Show when={tab() === "getstarted"}>
        <GetStartedPanel />
      </Show>

      {/* EMBEDDING is fully wired: serve-locally (download + serve a GGUF
          embedding model, bound to the embedding role) and the model-swap +
          reindex-status panel below both talk to the real backend. */}
      <Show when={tab() === "embedding"}>
        <Stack gap={6}>
          <EmbeddingServePanel />
          <EmbeddingPanel />
        </Stack>
      </Show>

      <Show when={tab() === "compare"}>
        <ComparePanel />
      </Show>
    </Stack>
  );
}
