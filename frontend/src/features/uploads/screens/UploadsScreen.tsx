import {
  createEffect,
  createMemo,
  createSignal,
  For,
  on,
  onCleanup,
  onMount,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import {
  Button,
  EmptyState,
  InstrumentBand,
  ListRow,
  LoadingText,
  PageHeader,
  Panel,
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
  useUploadDetail,
  refreshUploads,
  refreshUploadDetail,
  uploadFile,
  deleteUpload,
  retryUpload,
  setUploadKbExcluded,
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
  queued: { status: "idle", label: "Queued" },
  extracting: { status: "info", label: "Extracting" },
  done: { status: "nominal", label: "Done" },
  error: { status: "alert", label: "Error" },
};

export function UploadsScreen(): JSX.Element {
  const uploadsResource = useUploads();
  const uploads = () => uploadsResource() ?? [];
  const [selectedId, setSelectedId] = createSignal<string | null>(null);
  const detail = useUploadDetail(selectedId);

  const doneCount = () => uploads().filter((u) => u.status === "done").length;
  const extractingCount = () =>
    uploads().filter((u) => u.status === "extracting" || u.status === "queued")
      .length;
  const errorCount = () => uploads().filter((u) => u.status === "error").length;

  // Extraction runs off the request path on the backend, so poll the list while
  // anything is still queued/extracting. One stable interval (created once, not
  // recreated on every list refresh) that no-ops when nothing is in flight.
  const inFlight = () =>
    uploads().some((u) => u.status === "queued" || u.status === "extracting");
  onMount(() => {
    const timer = setInterval(() => {
      if (inFlight()) refreshUploads();
    }, 1500);
    onCleanup(() => clearInterval(timer));
  });

  // Refetch the open file's detail only when *its own* status changes — not on every
  // poll — so a selected DONE file isn't re-decrypted/re-sent every 1.5s while other
  // files are still extracting.
  const selectedStatus = createMemo(
    () => uploads().find((u) => u.id === selectedId())?.status,
  );
  createEffect(
    on(selectedStatus, () => {
      if (selectedId()) refreshUploadDetail();
    }),
  );

  async function handleUpload(files: File[]): Promise<void> {
    const results = await Promise.allSettled(files.map((f) => uploadFile(f)));
    const failed = results.filter((r) => r.status === "rejected").length;
    const ok = results.length - failed;
    if (ok) toast.success(`${ok} file${ok > 1 ? "s" : ""} uploaded`);
    if (failed) toast.error(`${failed} file${failed > 1 ? "s" : ""} failed`);
  }

  async function handleDelete(upload: Upload, e: MouseEvent): Promise<void> {
    e.stopPropagation();
    const ok = await confirm({
      title: `Delete "${upload.name}"?`,
      detail: "This permanently removes the file and its extracted text.",
      confirmLabel: "Delete",
      tone: "alert",
    });
    if (!ok) return;
    if (selectedId() === upload.id) setSelectedId(null);
    try {
      await deleteUpload(upload.id);
      toast.success(`Deleted "${upload.name}"`);
    } catch {
      toast.error(`Could not delete "${upload.name}"`);
    }
  }

  async function handleRetry(upload: Upload): Promise<void> {
    try {
      await retryUpload(upload.id);
      toast.info(`Re-extracting "${upload.name}"…`);
    } catch {
      toast.error("Could not retry extraction");
    }
  }

  async function handleToggleKb(upload: Upload, e: MouseEvent): Promise<void> {
    e.stopPropagation();
    const exclude = !upload.kbExcluded;
    try {
      await setUploadKbExcluded(upload.id, exclude);
      toast.success(
        exclude
          ? `Excluded "${upload.name}" from the knowledge base`
          : `Added "${upload.name}" to the knowledge base`,
      );
    } catch {
      toast.error("Could not update knowledge base membership");
    }
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="Uploads"
        subtitle="File storage with PDF text + vision extraction."
        assetId="ODY-UPL-01.0"
      />

      <Show when={uploads().length > 0}>
        <InstrumentBand
          items={[
            { label: "Total", value: String(uploads().length) },
            { label: "Done", value: String(doneCount()), tone: "nominal" },
            {
              label: "Extracting",
              value: String(extractingCount()),
              tone: "info",
            },
            { label: "Errors", value: String(errorCount()), tone: "alert" },
          ]}
        />
      </Show>

      <DropZone onFiles={(files) => void handleUpload(files)} />

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-5">
        {/* Upload list */}
        <div class="lg:col-span-2">
          <Panel label="Files" flush>
            <Suspense
              fallback={
                <div class="p-4">
                  <LoadingText />
                </div>
              }
            >
              <Show
                when={uploads().length > 0}
                fallback={
                  <EmptyState
                    icon="file"
                    message="No uploads"
                    hint="Drop files above or click BROWSE FILES."
                  />
                }
              >
                <For each={uploads()}>
                  {(upload) => {
                    const info = statusMap[upload.status];
                    return (
                      <ListRow
                        label={upload.name}
                        selected={selectedId() === upload.id}
                        onClick={() => setSelectedId(upload.id)}
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
                              label={
                                upload.kbExcluded
                                  ? "Excluded from knowledge base — click to include"
                                  : "In knowledge base — click to exclude"
                              }
                              side="left"
                            >
                              <Button
                                variant={
                                  upload.kbExcluded ? "ghost" : "default"
                                }
                                size="sm"
                                leading="database"
                                onClick={(e) => void handleToggleKb(upload, e)}
                                aria-label={
                                  upload.kbExcluded
                                    ? `Include ${upload.name} in knowledge base`
                                    : `Exclude ${upload.name} from knowledge base`
                                }
                              />
                            </Tooltip>
                            <Tooltip
                              label={`Delete "${upload.name}"`}
                              side="left"
                            >
                              <Button
                                variant="ghost"
                                size="sm"
                                leading="trash"
                                onClick={(e) => void handleDelete(upload, e)}
                                aria-label={`Delete ${upload.name}`}
                              />
                            </Tooltip>
                          </Row>
                        }
                      />
                    );
                  }}
                </For>
              </Show>
            </Suspense>
          </Panel>
        </div>

        {/* Detail panel */}
        <div class="lg:col-span-3">
          <Show
            when={selectedId()}
            fallback={
              <EmptyState
                icon="file"
                message="Select a file"
                hint="Choose a file from the list to view its extracted text."
              />
            }
          >
            <Suspense fallback={<LoadingText label="Loading file" />}>
              <Show when={detail()}>
                {(upload) => (
                  <Show
                    when={upload().status === "done"}
                    fallback={
                      <Show
                        when={upload().status === "error"}
                        fallback={
                          <EmptyState
                            icon="clock"
                            message={
                              upload().status === "extracting"
                                ? "Extracting…"
                                : "Queued"
                            }
                            hint="Extraction in progress. This updates automatically."
                          />
                        }
                      >
                        <EmptyState
                          icon="warning"
                          message="Extraction failed"
                          hint={
                            upload().note ??
                            "Extraction failed. Retry below or try a different file."
                          }
                          action={
                            <Button
                              variant="default"
                              leading="refresh"
                              onClick={() => void handleRetry(upload())}
                            >
                              Retry extraction
                            </Button>
                          }
                        />
                      </Show>
                    }
                  >
                    <UploadDetailPanel upload={upload()} />
                  </Show>
                )}
              </Show>
            </Suspense>
          </Show>
        </div>
      </div>
    </Stack>
  );
}
