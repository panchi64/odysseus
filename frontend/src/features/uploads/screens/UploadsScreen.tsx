import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  EmptyState,
  InstrumentBand,
  ListRow,
  LoadingText,
  PageHeader,
  Panel,
  ProgressBar,
  Row,
  Stack,
  StatusFlag,
  Text,
} from "~/ui";
import { bytes } from "~/lib/format";
import { useUploads } from "../data";
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

  const doneCount = () =>
    (uploads() ?? []).filter((u) => u.status === "done").length;
  const extractingCount = () =>
    (uploads() ?? []).filter((u) => u.status === "extracting").length;
  const errorCount = () =>
    (uploads() ?? []).filter((u) => u.status === "error").length;

  return (
    <Stack gap={6}>
      <PageHeader
        title="UPLOADS"
        subtitle="PDF extraction, OCR, and form field detection."
        assetId="ODY-UPL-01.0"
        actions={
          <Button variant="primary" leading="upload">
            UPLOAD
          </Button>
        }
      />

      <Suspense fallback={<LoadingText />}>
        <Show when={uploads()}>
          <InstrumentBand
            items={[
              { label: "TOTAL", value: String((uploads() ?? []).length) },
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
      </Suspense>

      <DropZone />

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-5">
        {/* Upload list */}
        <div class="lg:col-span-2">
          <Panel label="FILES" flush>
            <Suspense
              fallback={
                <div class="p-3">
                  <LoadingText />
                </div>
              }
            >
              <Show
                when={(uploads() ?? []).length}
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
            </Suspense>
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
            {(upload) => (
              <Show
                when={upload().status === "done"}
                fallback={
                  <EmptyState
                    icon="clock"
                    message={
                      upload().status === "extracting"
                        ? "EXTRACTING…"
                        : upload().status === "queued"
                          ? "QUEUED"
                          : "EXTRACTION FAILED"
                    }
                    hint={
                      upload().status === "error"
                        ? "Extraction failed. Try re-uploading or use a different file."
                        : "Extraction in progress. Check back shortly."
                    }
                  />
                }
              >
                <UploadDetailPanel upload={upload()} />
              </Show>
            )}
          </Show>
        </div>
      </div>
    </Stack>
  );
}
