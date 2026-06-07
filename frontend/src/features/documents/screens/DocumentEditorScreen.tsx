import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  Divider,
  EditorShell,
  ListRow,
  LoadingText,
  Modal,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
  Textarea,
  confirm,
  toast,
} from "~/ui";
import { timestamp } from "~/lib/format";
import { createAiAssistStream, useDocumentDetail } from "../data";
import type { DocVersion } from "../model";

export function DocumentEditorScreen(props: { id: string }): JSX.Element {
  const detail = useDocumentDetail(() => props.id);
  const [body, setBody] = createSignal<string | undefined>(undefined);
  // Tracks the last-saved snapshot so isDirty compares against it, not the
  // original mock body (which never updates in Phase 1).
  const [savedSnapshot, setSavedSnapshot] = createSignal<string | undefined>(
    undefined,
  );
  const [showSaved, setShowSaved] = createSignal(false);
  const assist = createAiAssistStream();

  // Version preview modal
  const [previewVersion, setPreviewVersion] = createSignal<DocVersion | null>(
    null,
  );

  // Seed body once when detail loads
  let seeded = false;
  const getBody = () => {
    if (!seeded && detail()?.body) {
      seeded = true;
      setBody(detail()!.body);
    }
    return body() ?? detail()?.body ?? "";
  };

  const isDirty = () => {
    const baseline = savedSnapshot() ?? detail()?.body ?? "";
    return getBody() !== baseline;
  };

  function handleSave(): void {
    if (!isDirty()) return;
    // Phase 1: mock save — persist snapshot and show feedback
    setSavedSnapshot(getBody());
    setShowSaved(true);
    toast.success("Document saved");
    setTimeout(() => setShowSaved(false), 2000);
  }

  async function handleRestoreVersion(v: DocVersion): Promise<void> {
    const ok = await confirm({
      title: `Restore "${v.label}"?`,
      detail: "This will replace the current document body with this snapshot.",
      confirmLabel: "RESTORE",
      tone: "alert",
    });
    if (!ok) return;
    setBody(v.body);
    setPreviewVersion(null);
    toast.success(`Restored to ${v.label}`);
  }

  const toolsPanel = () => (
    <>
      <Panel label="VERSION HISTORY" flush>
        <For each={detail()?.versions ?? []}>
          {(v) => (
            <ListRow
              label={v.label}
              leading="clock"
              onClick={() => setPreviewVersion(v)}
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
                <Text variant="body" tone="default" class="whitespace-pre-wrap">
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
                      setBody((b) => (b ?? "") + "\n\n" + assist.suggestion())
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
    </>
  );

  return (
    <Suspense fallback={<LoadingText label="LOADING DOCUMENT" />}>
      <EditorShell
        backHref="/documents"
        backLabel="BACK TO DOCUMENTS"
        title={detail()?.title ?? "—"}
        dirty={isDirty()}
        meta={
          <Text variant="micro" tone="dim">
            {detail()?.words ?? 0} WORDS · UPDATED{" "}
            {detail() ? timestamp(detail()!.updatedAt) : "—"}
          </Text>
        }
        status={
          <StatusFlag
            status={detail()?.status === "active" ? "nominal" : "idle"}
          >
            {(detail()?.status ?? "active").toUpperCase()}
          </StatusFlag>
        }
        actions={
          <Button
            variant={showSaved() ? "default" : "primary"}
            leading={showSaved() ? "check" : "download"}
            size="sm"
            disabled={!isDirty()}
            onClick={handleSave}
          >
            {showSaved() ? "SAVED" : "SAVE"}
          </Button>
        }
        aside={toolsPanel}
      >
        <Textarea
          value={getBody()}
          onInput={(e) => setBody(e.currentTarget.value)}
          rows={32}
          class="h-full w-full resize-none font-mono text-body"
        />
      </EditorShell>

      {/* Version preview modal */}
      <Show when={previewVersion()}>
        {(v) => (
          <Modal
            open={true}
            onClose={() => setPreviewVersion(null)}
            title={v().label}
            class="max-w-2xl"
            footer={
              <>
                <Button variant="ghost" onClick={() => setPreviewVersion(null)}>
                  CLOSE
                </Button>
                <Button
                  variant="danger"
                  leading="clock"
                  onClick={() => void handleRestoreVersion(v())}
                >
                  RESTORE THIS VERSION
                </Button>
              </>
            }
          >
            <Stack gap={3}>
              <Text variant="micro" tone="dim">
                {v().author} · {timestamp(v().createdAt)}
              </Text>
              <div class="border border-line bg-raised p-3">
                <Text
                  variant="body"
                  tone="default"
                  class="whitespace-pre-wrap font-mono"
                >
                  {v().body}
                </Text>
              </div>
            </Stack>
          </Modal>
        )}
      </Show>
    </Suspense>
  );
}
