import {
  createSignal,
  createEffect,
  createMemo,
  on,
  For,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import {
  Button,
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
  Tooltip,
  confirm,
  toast,
} from "~/ui";
import { timestamp } from "~/lib/format";
import {
  restoreDocumentVersion,
  saveDocument,
  useDocumentDetail,
} from "../data";
import { lineDiff } from "../diff";
import { DocumentDiff } from "../components/DocumentDiff";
import { RenameDialog } from "../components/RenameDialog";
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

  // Version diff modal
  const [previewVersion, setPreviewVersion] = createSignal<DocVersion | null>(
    null,
  );
  const [renameOpen, setRenameOpen] = createSignal(false);

  // Seed body once when detail loads. Reset when the document id changes so a reused
  // editor instance doesn't keep the previous document's draft.
  let seeded = false;
  createEffect(
    on(
      () => props.id,
      () => {
        seeded = false;
        setBody(undefined);
        setSavedSnapshot(undefined);
      },
      { defer: true },
    ),
  );
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

  async function handleSave(): Promise<void> {
    if (!isDirty()) return;
    const next = getBody();
    try {
      await saveDocument(props.id, { body: next });
      setSavedSnapshot(next);
      setShowSaved(true);
      toast.success("Document saved");
      setTimeout(() => setShowSaved(false), 2000);
    } catch {
      toast.error("Could not save document");
    }
  }

  async function handleRename(title: string): Promise<void> {
    await saveDocument(props.id, { title });
    toast.success(`Renamed to "${title}"`);
  }

  async function handleRestoreVersion(v: DocVersion): Promise<void> {
    const ok = await confirm({
      title: `Restore "${v.label}"?`,
      detail: "This will replace the current document body with this snapshot.",
      confirmLabel: "RESTORE",
      tone: "alert",
    });
    if (!ok) return;
    try {
      await restoreDocumentVersion(props.id, v.version);
      // Reflect the restored body locally so the editor isn't left dirty against it.
      setBody(v.body);
      setSavedSnapshot(v.body);
      setPreviewVersion(null);
      toast.success(`Restored to ${v.label}`);
    } catch {
      toast.error("Could not restore version");
    }
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

      {/* AI Assist — DOC-3 (streaming rewrite/suggest) lands in a later slice. */}
      <Panel label="AI ASSIST">
        <Tooltip label="Available in Phase 2">
          <Row gap={2} wrap>
            <Button variant="default" size="sm" leading="pen" disabled>
              REWRITE
            </Button>
            <Button variant="default" size="sm" leading="note" disabled>
              SUMMARIZE
            </Button>
            <Button variant="default" size="sm" leading="compare" disabled>
              SUGGEST
            </Button>
          </Row>
        </Tooltip>
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
          <>
            <Button
              variant="ghost"
              leading="pen"
              size="sm"
              onClick={() => setRenameOpen(true)}
            >
              RENAME
            </Button>
            <Button
              variant={showSaved() ? "default" : "primary"}
              leading={showSaved() ? "check" : "download"}
              size="sm"
              disabled={!isDirty()}
              onClick={() => void handleSave()}
            >
              {showSaved() ? "SAVED" : "SAVE"}
            </Button>
          </>
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

      {/* Version diff modal — what this version changed vs. the one before it. */}
      <Show when={previewVersion()}>
        {(v) => {
          // The predecessor snapshot (version N-1); the first version diffs
          // against an empty document, so its diff is the initial content.
          const prev = createMemo(() =>
            (detail()?.versions ?? []).find(
              (x) => x.version === v().version - 1,
            ),
          );
          const result = createMemo(() =>
            lineDiff(prev()?.body ?? "", v().body),
          );
          return (
            <Modal
              open={true}
              onClose={() => setPreviewVersion(null)}
              title={`CHANGES IN ${v().label}`}
              class="max-w-3xl"
              footer={
                <>
                  <Button
                    variant="ghost"
                    onClick={() => setPreviewVersion(null)}
                  >
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
                <Row gap={3} align="center">
                  <Text variant="micro" tone="dim">
                    {v().author} · {timestamp(v().createdAt)} · vs{" "}
                    {prev()?.label ?? "EMPTY"}
                  </Text>
                  <Row gap={2} align="center">
                    <Text variant="micro" tone="nominal" class="tabular-nums">
                      +{result().added}
                    </Text>
                    <Text variant="micro" tone="alert" class="tabular-nums">
                      −{result().removed}
                    </Text>
                  </Row>
                </Row>
                <DocumentDiff result={result()} />
              </Stack>
            </Modal>
          );
        }}
      </Show>

      <RenameDialog
        open={renameOpen()}
        currentTitle={detail()?.title ?? ""}
        onClose={() => setRenameOpen(false)}
        onSubmit={handleRename}
      />
    </Suspense>
  );
}
