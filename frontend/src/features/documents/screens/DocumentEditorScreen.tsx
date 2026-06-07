import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  Divider,
  ListRow,
  LoadingText,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
  Textarea,
} from "~/ui";
import { timestamp } from "~/lib/format";
import { createAiAssistStream, useDocumentDetail } from "../data";

export function DocumentEditorScreen(props: { id: string }): JSX.Element {
  const detail = useDocumentDetail(() => props.id);
  const [body, setBody] = createSignal<string | undefined>(undefined);
  const assist = createAiAssistStream();

  // Seed body once when detail loads
  let seeded = false;
  const getBody = () => {
    if (!seeded && detail()?.body) {
      seeded = true;
      setBody(detail()!.body);
    }
    return body() ?? detail()?.body ?? "";
  };

  return (
    <Suspense fallback={<LoadingText label="LOADING DOCUMENT" />}>
      <div class="flex h-full min-h-0 gap-4">
        {/* Editor */}
        <section class="flex min-w-0 flex-1 flex-col gap-3">
          <header class="flex items-center justify-between gap-3 border-b border-line pb-3">
            <Stack gap={0}>
              <Text variant="readout" tone="bright">
                {detail()?.title ?? "—"}
              </Text>
              <Text variant="micro" tone="dim">
                {detail()?.words ?? 0} WORDS · UPDATED{" "}
                {detail() ? timestamp(detail()!.updatedAt) : "—"}
              </Text>
            </Stack>
            <Row gap={2}>
              <StatusFlag
                status={detail()?.status === "active" ? "nominal" : "idle"}
              >
                {(detail()?.status ?? "active").toUpperCase()}
              </StatusFlag>
              <Button variant="primary" leading="download" size="sm">
                SAVE
              </Button>
            </Row>
          </header>

          <div class="min-h-0 flex-1">
            <Textarea
              value={getBody()}
              onInput={(e) => setBody(e.currentTarget.value)}
              rows={32}
              class="h-full w-full resize-none font-mono text-body"
            />
          </div>
        </section>

        {/* Right panel */}
        <aside class="hidden w-72 shrink-0 flex-col gap-4 lg:flex">
          {/* Version history */}
          <Panel label="VERSION HISTORY" flush>
            <For each={detail()?.versions ?? []}>
              {(v) => (
                <ListRow
                  label={v.label}
                  leading="clock"
                  right={
                    <Text variant="micro" tone="dim">
                      {timestamp(v.createdAt).slice(0, 10)}
                    </Text>
                  }
                />
              )}
            </For>
          </Panel>

          {/* AI Assist */}
          <Panel label="AI ASSIST">
            <Stack gap={3}>
              <Row gap={2} wrap>
                <Button
                  variant="default"
                  size="sm"
                  leading="pen"
                  onClick={() => assist.runAssist("rewrite")}
                  disabled={assist.streaming()}
                >
                  REWRITE
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  leading="note"
                  onClick={() => assist.runAssist("summarize")}
                  disabled={assist.streaming()}
                >
                  SUMMARIZE
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  leading="compare"
                  onClick={() => assist.runAssist("suggest")}
                  disabled={assist.streaming()}
                >
                  SUGGEST
                </Button>
              </Row>

              <Show when={assist.suggestion() || assist.streaming()}>
                <Divider />
                <div class="flex flex-col gap-2">
                  <Row gap={2} align="center">
                    <StatusFlag
                      status={assist.streaming() ? "info" : "nominal"}
                      dot={assist.streaming()}
                    >
                      {assist.streaming() ? "GENERATING" : "SUGGESTION"}
                    </StatusFlag>
                  </Row>
                  <div class="border border-line bg-raised p-3">
                    <Text
                      variant="body"
                      tone="default"
                      class="whitespace-pre-wrap"
                    >
                      {assist.suggestion()}
                      {assist.streaming() && (
                        <span class="animate-pulse text-info">▌</span>
                      )}
                    </Text>
                  </div>
                  <Show when={!assist.streaming() && assist.suggestion()}>
                    <Row gap={2}>
                      <Button
                        variant="primary"
                        size="sm"
                        leading="check"
                        onClick={() =>
                          setBody(
                            (b) => (b ?? "") + "\n\n" + assist.suggestion(),
                          )
                        }
                      >
                        APPLY
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => assist.runAssist("dismiss")}
                      >
                        DISMISS
                      </Button>
                    </Row>
                  </Show>
                </div>
              </Show>
            </Stack>
          </Panel>
        </aside>
      </div>
    </Suspense>
  );
}
