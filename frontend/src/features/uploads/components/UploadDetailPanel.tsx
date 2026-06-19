import { createMemo, createSignal, Show, type JSX } from "solid-js";
import {
  Button,
  Field,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
  Textarea,
  toast,
} from "~/ui";
import { bytes } from "~/lib/format";
import { correctUploadText, downloadUpload } from "../data";
import type { Upload } from "../model";

interface UploadDetailPanelProps {
  upload: Upload;
}

/** A human label + tone for which extractor produced the text. "basic" extractions
 *  are candidates for a future MinerU re-run, so they read as a muted hint. */
function extractorFlag(
  extractor: string | undefined,
): { label: string; status: "nominal" | "info" | "idle" } | null {
  if (extractor === "mineru") return { label: "MINERU", status: "nominal" };
  if (extractor === "manual") return { label: "EDITED", status: "info" };
  if (extractor === "basic") return { label: "BUILT-IN", status: "idle" };
  return null;
}

export function UploadDetailPanel(props: UploadDetailPanelProps): JSX.Element {
  const [extractedText, setExtractedText] = createSignal(
    props.upload.extractedText ?? "",
  );
  const [saving, setSaving] = createSignal(false);

  const isTextDirty = createMemo(
    () => extractedText() !== (props.upload.extractedText ?? ""),
  );

  async function handleSaveText(): Promise<void> {
    setSaving(true);
    try {
      await correctUploadText(props.upload.id, extractedText());
      toast.success("Extracted text saved");
    } catch {
      toast.error("Could not save text");
    } finally {
      setSaving(false);
    }
  }

  async function handleExport(): Promise<void> {
    try {
      await downloadUpload(props.upload.id, props.upload.name);
    } catch {
      toast.error("Could not download file");
    }
  }

  const flag = () => extractorFlag(props.upload.extractor);

  return (
    <Panel
      label="DOCUMENT DETAIL"
      meta={
        <Row gap={2} align="center">
          <Show when={props.upload.vision}>
            <StatusFlag status="info">VISION</StatusFlag>
          </Show>
          <Show when={flag()}>
            {(f) => <StatusFlag status={f().status}>{f().label}</StatusFlag>}
          </Show>
          <Text variant="micro" tone="dim">
            {bytes(props.upload.sizeBytes)}
          </Text>
        </Row>
      }
    >
      <Stack gap={4}>
        <Stack gap={1}>
          <Text variant="label" tone="bright">
            {props.upload.name}
          </Text>
          <Row gap={2}>
            <Field label="TYPE" value={props.upload.mime} orientation="row" />
          </Row>
          <Show when={props.upload.note}>
            <Text variant="micro" tone="warn">
              {props.upload.note}
            </Text>
          </Show>
        </Stack>

        <Stack gap={2}>
          <Row gap={2} justify="between" align="center">
            <Row gap={2} align="center">
              <Text variant="label" tone="dim">
                EXTRACTED TEXT
              </Text>
              <Text variant="micro" tone="dim">
                Edit to correct extraction errors
              </Text>
              <Show when={isTextDirty()}>
                <StatusFlag status="warn">UNSAVED</StatusFlag>
              </Show>
            </Row>
            <Row gap={2} align="center">
              <Button
                variant="ghost"
                size="sm"
                leading="download"
                onClick={() => void handleExport()}
              >
                EXPORT
              </Button>
              <Button
                variant="primary"
                size="sm"
                leading="check"
                disabled={!isTextDirty() || saving()}
                onClick={() => void handleSaveText()}
              >
                SAVE
              </Button>
            </Row>
          </Row>
          <Textarea
            rows={14}
            value={extractedText()}
            onInput={(e) => setExtractedText(e.currentTarget.value)}
            label="EXTRACTED TEXT"
          />
        </Stack>
      </Stack>
    </Panel>
  );
}
