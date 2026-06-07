import { createSignal, For, Show, type JSX } from "solid-js";
import {
  Button,
  EmptyState,
  InstrumentBand,
  ListRow,
  PageHeader,
  Panel,
  ProgressBar,
  Row,
  Stack,
  StatusFlag,
  Text,
  Tooltip,
  confirm,
  toast,
} from "~/ui";
import { bytes } from "~/lib/format";
import {
  useUploads,
  removeUpload,
  restoreUpload,
  retryExtraction,
} from "../data";
import { DropZone } from "../components/DropZone";
import { UploadDetailPanel } from "../components/UploadDetailPanel";
import type { Upload, UploadStatus } from "../model";

const statusMap: Record<
  UploadStatus,
  {
    status: "idle" | "live" | "nominal" | "warn" | "alert" | "info";
    label: string;
  }
> = {
  queued: { status: "idle", label: "QUEUED" },
  extracting: { status: "info", label: "EXTRACTING" },
  done: { status: "nominal", label: "DONE" },
  error: { status: "alert", label: "ERROR" },
};

export function UploadsScreen(): JSX.Element {
  const uploads = useUploads();
  const [selected, setSelected] = createSignal<Upload | null>(null);

  const doneCount = () => uploads().filter((u) => u.status === "done").length;
  const extractingCount = () =>
    uploads().filter((u) => u.status === "extracting").length;
  const errorCount = () => uploads().filter((u) => u.status === "error").length;

  async function handleDelete(upload: Upload, e: MouseEvent) {
    e.stopPropagation();
    const ok = await confirm({
      title: `Delete "${upload.name}"?`,
      detail: "This cannot be undone.",
      confirmLabel: "DELETE",
      tone: "alert",
    });
    if (!ok) return;

    if (selected()?.id === upload.id) setSelected(null);
    removeUpload(upload.id);
    toast.success(`Deleted "${upload.name}"`, {
      action: {
        label: "UNDO",
        onClick: () => {
          restoreUpload(upload);
          toast.success(`Restored "${upload.name}"`);
        },
      },
    });
  }

  function handleRetry(upload: Upload) {
    retryExtraction(upload.id);
    // Update selected to reflect new status from the reactive store
    setSelected(null);
    toast.info(`Retrying extraction for "${upload.name}"…`);
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="UPLOADS"
        subtitle="PDF extraction, OCR, and form field detection."
        assetId="ODY-UPL-01.0"
        actions={
          <Tooltip label="File upload available in Phase 2" side="bottom">
            <Button variant="primary" leading="upload" disabled>
              UPLOAD
            </Button>
          </Tooltip>
        }
      />

      <Show when={uploads().length > 0}>
        <InstrumentBand
          items={[
            { label: "TOTAL", value: String(uploads().length) },
            { label: "DONE", value: String(doneCount()), tone: "nominal" },
            {
              label: "EXTRACTING",
              value: String(extractingCount()),
              tone: "info",
            },
            { label: "ERRORS", value: String(errorCount()), tone: "alert" },
          ]}
        />
      </Show>

      <DropZone />

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-5">
        {/* Upload list */}
        <div class="lg:col-span-2">
          <Panel label="FILES" flush>
            <Show
              when={uploads().length > 0}
              fallback={
                <EmptyState
                  icon="file"
                  message="NO UPLOADS"
                  hint="Drop files above or click UPLOAD."
                />
              }
            >
              <For each={uploads()}>
                {(upload) => {
                  const info = statusMap[upload.status];
                  return (
                    <Stack gap={0}>
                      <ListRow
                        label={upload.name}
                        selected={selected()?.id === upload.id}
                        onClick={() => setSelected(upload)}
                        leading="file"
                        right={
                          <Row gap={2} align="center">
                            <Text variant="micro" tone="dim">
                              {bytes(upload.sizeBytes)}
                            </Text>
                            <StatusFlag status={info.status}>
                              {info.label}
                            </StatusFlag>
                            <Tooltip
                              label={`Delete "${upload.name}"`}
                              side="left"
                            >
                              <Button
                                variant="ghost"
                                size="sm"
                                leading="trash"
                                onClick={(e) => handleDelete(upload, e)}
                                aria-label={`Delete ${upload.name}`}
                              />
                            </Tooltip>
                          </Row>
                        }
                      />
                      <Show when={upload.status === "extracting"}>
                        <div class="px-3 pb-2">
                          <ProgressBar
                            value={upload.extractionProgress}
                            tone="info"
                            showValue
                          />
                        </div>
                      </Show>
                    </Stack>
                  );
                }}
              </For>
            </Show>
          </Panel>
        </div>

        {/* Detail panel */}
        <div class="lg:col-span-3">
          <Show
            when={selected()}
            fallback={
              <EmptyState
                icon="file"
                message="SELECT A FILE"
                hint="Choose a document from the list to view extracted content and form fields."
              />
            }
          >
            {(upload) => {
              // Derive the live upload from the store so status changes reflect
              const liveUpload = () =>
                uploads().find((u) => u.id === upload().id) ?? upload();

              return (
                <Show
                  when={liveUpload().status === "done"}
                  fallback={
                    <Show
                      when={liveUpload().status === "error"}
                      fallback={
                        <EmptyState
                          icon="clock"
                          message={
                            liveUpload().status === "extracting"
                              ? "EXTRACTING…"
                              : "QUEUED"
                          }
                          hint="Extraction in progress. Check back shortly."
                        />
                      }
                    >
                      <EmptyState
                        icon="warning"
                        message="EXTRACTION FAILED"
                        hint="Extraction failed. Retry below or try a different file."
                        action={
                          <Button
                            variant="default"
                            leading="refresh"
                            onClick={() => handleRetry(liveUpload())}
                          >
                            RETRY EXTRACTION
                          </Button>
                        }
                      />
                    </Show>
                  }
                >
                  <UploadDetailPanel upload={liveUpload()} />
                </Show>
              );
            }}
          </Show>
        </div>
      </div>
    </Stack>
  );
}
