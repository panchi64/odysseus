import { createSignal, For, Show, type JSX } from "solid-js";
import {
  Button,
  Field,
  Input,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Tabs,
  Text,
  Textarea,
} from "~/ui";
import { bytes } from "~/lib/format";
import type { Upload } from "../model";

interface UploadDetailPanelProps {
  upload: Upload;
}

export function UploadDetailPanel(props: UploadDetailPanelProps): JSX.Element {
  const [tab, setTab] = createSignal("text");
  const [extractedText, setExtractedText] = createSignal(
    props.upload.extractedText ?? "",
  );
  const [formValues, setFormValues] = createSignal<Record<string, string>>(
    Object.fromEntries(
      (props.upload.formFields ?? []).map((f) => [f.name, f.value]),
    ),
  );

  return (
    <Panel
      label="DOCUMENT DETAIL"
      meta={
        <Row gap={2} align="center">
          <Show when={props.upload.vision}>
            <StatusFlag status="info">VISION</StatusFlag>
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
        </Stack>

        <Tabs
          items={[
            { value: "text", label: "EXTRACTED TEXT" },
            { value: "fields", label: "FORM FIELDS" },
          ]}
          value={tab()}
          onChange={setTab}
        />

        <Show when={tab() === "text"}>
          <Stack gap={2}>
            <Row gap={2} justify="between" align="center">
              <Text variant="micro" tone="dim">
                OCR output — edit to correct errors
              </Text>
              <Button variant="ghost" size="sm" leading="download">
                EXPORT
              </Button>
            </Row>
            <Textarea
              rows={12}
              value={extractedText()}
              onInput={(e) => setExtractedText(e.currentTarget.value)}
              label="EXTRACTED TEXT"
            />
          </Stack>
        </Show>

        <Show when={tab() === "fields"}>
          <Show
            when={(props.upload.formFields ?? []).length > 0}
            fallback={
              <Text tone="dim" variant="micro">
                No fillable form fields detected.
              </Text>
            }
          >
            <Stack gap={2}>
              <For each={props.upload.formFields}>
                {(field) => (
                  <Input
                    label={field.name.toUpperCase()}
                    value={formValues()[field.name] ?? ""}
                    onInput={(e) =>
                      setFormValues((prev) => ({
                        ...prev,
                        [field.name]: e.currentTarget.value,
                      }))
                    }
                    placeholder="—"
                  />
                )}
              </For>
              <Row justify="end">
                <Button variant="primary" leading="check">
                  SAVE FIELDS
                </Button>
              </Row>
            </Stack>
          </Show>
        </Show>
      </Stack>
    </Panel>
  );
}
