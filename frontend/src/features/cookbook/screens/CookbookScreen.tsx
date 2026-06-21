import { createSignal, Show, Suspense, type JSX } from "solid-js";
import {
  EmptyState,
  InstrumentBand,
  LoadingText,
  NotConnectedOverlay,
  PageHeader,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Tabs,
  Text,
} from "~/ui";
import { useHardware } from "../data";
import { EmbeddingPanel } from "../components/EmbeddingPanel";
import { ComparePanel } from "../components/ComparePanel";
import { GetStartedPanel } from "../components/GetStartedPanel";

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

      {/* LOCAL MODELS shows the live hardware readout (above) plus a signpost: local
          download & serve isn't wired yet, so it points to Get Started and external
          model catalogues rather than a leaderboard. */}
      <Show when={tab() === "local"}>
        <Panel label="LOCAL MODELS" flush>
          <EmptyState
            icon="cpu"
            message="LOCAL SERVE COMING SOON"
            hint="Local download & serve is coming. To run a model now, set one up in Get Started."
            action={
              <Row gap={4} align="center">
                <a
                  href="https://huggingface.co/models"
                  target="_blank"
                  rel="noreferrer noopener"
                  class="underline-offset-2 hover:underline"
                >
                  <Text variant="label" tone="info">
                    Browse models online ↗
                  </Text>
                </a>
                <a
                  href="https://openrouter.ai/models"
                  target="_blank"
                  rel="noreferrer noopener"
                  class="underline-offset-2 hover:underline"
                >
                  <Text variant="label" tone="info">
                    OpenRouter models ↗
                  </Text>
                </a>
              </Row>
            }
          />
        </Panel>
      </Show>

      <Show when={tab() === "getstarted"}>
        <GetStartedPanel />
      </Show>

      <Show when={tab() === "embedding"}>
        <div class="relative">
          <EmbeddingPanel />
          <NotConnectedOverlay />
        </div>
      </Show>

      <Show when={tab() === "compare"}>
        <ComparePanel />
      </Show>
    </Stack>
  );
}
