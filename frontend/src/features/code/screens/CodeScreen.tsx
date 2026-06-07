import { For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  EmptyState,
  ListRow,
  LoadingText,
  PageHeader,
  Panel,
  Row,
  Select,
  Stack,
  StatusFlag,
  Text,
  Textarea,
  toast,
  Tooltip,
} from "~/ui";
import { relativeTime, pad } from "~/lib/format";
import { useCodeRuns, createCodeRunner } from "../data";

const LANGUAGE_OPTIONS = [
  { value: "python", label: "Python 3" },
  { value: "javascript", label: "JavaScript" },
  { value: "html", label: "HTML" },
];

export function CodeScreen(): JSX.Element {
  const runs = useCodeRuns();
  const {
    language,
    setLanguage,
    source,
    setSource,
    running,
    outputLines,
    lastStatus,
    lastDuration,
    history,
    runCode,
    cancelRun,
    resetToTemplate,
  } = createCodeRunner(runs);

  function handleCopyError() {
    const errorText = outputLines().join("\n");
    void navigator.clipboard.writeText(errorText).then(() => {
      toast.success("Error copied to clipboard");
    });
  }

  function handleReset() {
    resetToTemplate();
    toast.info("Editor reset to template");
  }

  function handleCancel() {
    cancelRun();
    toast.warn("Execution cancelled");
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="CODE RUNNER"
        subtitle="Execute scripts in-browser. Runs in-browser, not on host."
        assetId="ODY-CODE-01.0"
        actions={
          <Text variant="micro" tone="dim" class="border border-line px-2 py-1">
            SANDBOXED · IN-BROWSER
          </Text>
        }
      />

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Editor + output */}
        <div class="flex flex-col gap-4 lg:col-span-2">
          <Panel
            label="EDITOR"
            meta={
              <Row gap={2} align="center">
                <Select
                  options={LANGUAGE_OPTIONS}
                  value={language()}
                  onChange={setLanguage}
                />
                <Tooltip label="Reset editor to the starter template for this language">
                  <Button
                    variant="ghost"
                    leading="refresh"
                    disabled={running()}
                    onClick={handleReset}
                  >
                    RESET
                  </Button>
                </Tooltip>
                <Show
                  when={running()}
                  fallback={
                    <Button variant="primary" leading="play" onClick={runCode}>
                      RUN
                    </Button>
                  }
                >
                  <Button
                    variant="danger"
                    leading="stop"
                    onClick={handleCancel}
                  >
                    CANCEL
                  </Button>
                </Show>
              </Row>
            }
          >
            <Textarea
              rows={14}
              value={source()}
              onInput={(e) => setSource(e.currentTarget.value)}
              class="font-mono text-sm"
            />
          </Panel>

          <Panel
            label="OUTPUT"
            state={lastStatus() === "error" ? "alert" : undefined}
            meta={
              <Show when={lastStatus()}>
                <Row gap={2} align="center">
                  <StatusFlag
                    status={lastStatus() === "ok" ? "nominal" : "alert"}
                  >
                    {lastStatus()?.toUpperCase() ?? ""}
                  </StatusFlag>
                  <Show when={lastDuration() !== null}>
                    <Text variant="micro" tone="dim">
                      {lastDuration()} MS
                    </Text>
                  </Show>
                  <Show when={lastStatus() === "error"}>
                    <Button variant="ghost" onClick={handleCopyError}>
                      COPY ERROR
                    </Button>
                  </Show>
                </Row>
              </Show>
            }
          >
            <Show
              when={running() || outputLines().length > 0}
              fallback={
                <EmptyState
                  icon="terminal"
                  message="NO OUTPUT"
                  hint="Press RUN to execute the script."
                />
              }
            >
              <div class="font-mono text-xs text-nominal bg-bg border border-line p-3 min-h-24 whitespace-pre-wrap">
                <For each={outputLines()}>{(line) => <div>{line}</div>}</For>
                <Show when={running()}>
                  <LoadingText label="EXECUTING" />
                </Show>
              </div>
              <Show when={lastStatus() === "error"}>
                <Text variant="micro" tone="dim" class="pt-2">
                  Fix your code above and press RUN to try again.
                </Text>
              </Show>
            </Show>
          </Panel>

          <Text variant="micro" tone="dim" class="text-center">
            Runs in-browser (Pyodide / native JS) — code does not execute on the
            Odysseus host server.
          </Text>
        </div>

        {/* Run history */}
        <div class="lg:col-span-1">
          <Panel label="RUN HISTORY" flush>
            <Suspense
              fallback={
                <div class="p-3">
                  <LoadingText />
                </div>
              }
            >
              <Show
                when={history().length > 0}
                fallback={
                  <EmptyState
                    icon="clock"
                    message="NO HISTORY"
                    hint="Past runs appear here."
                  />
                }
              >
                <For each={history()}>
                  {(run) => (
                    <ListRow
                      label={`${run.language.toUpperCase()} · ${pad(run.durationMs, 4)} MS`}
                      leading={run.status === "ok" ? "check" : "warning"}
                      right={
                        <Row gap={2} align="center">
                          <StatusFlag
                            status={run.status === "ok" ? "nominal" : "alert"}
                          >
                            {run.status.toUpperCase()}
                          </StatusFlag>
                          <Text variant="micro" tone="dim">
                            {relativeTime(run.ranAt)}
                          </Text>
                        </Row>
                      }
                    />
                  )}
                </For>
              </Show>
            </Suspense>
          </Panel>
        </div>
      </div>
    </Stack>
  );
}
