import { createEffect, createResource, createSignal, type JSX } from "solid-js";
import { Button, PathInput, Panel, Row, Stack, Text, toast } from "~/ui";
import { fetchModelsDir, updateModelsDir, usePathPicker } from "../serving";

/** Where new model downloads are written. Loads the current dir and lets the
 *  operator point it elsewhere. Validation is the backend's job — it returns 400
 *  with a reason — so the only client-side gate is non-empty; the displayed value
 *  refreshes from the stored absolute path the backend returns. */
export function ModelsDirSection(): JSX.Element {
  const [dir, { mutate }] = createResource(fetchModelsDir);
  const [value, setValue] = createSignal("");
  const [saving, setSaving] = createSignal(false);
  const picker = usePathPicker();

  // Prefill the field once the current dir loads (and on a successful save).
  createEffect(() => {
    const current = dir.latest;
    if (current != null) setValue(current);
  });

  const canSave = () => value().trim().length > 0 && !saving();

  async function save(): Promise<void> {
    if (!canSave()) return;
    setSaving(true);
    try {
      const stored = await updateModelsDir(value().trim());
      mutate(stored);
      setValue(stored);
      toast.success("Models directory updated");
    } catch (err) {
      // Keep the operator's input so they can correct and retry — the stored value
      // didn't change, so don't refetch (it would overwrite the field via the effect).
      toast.error(
        (err as { detail?: string })?.detail ??
          "Couldn't update the models directory",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Panel label="Models directory">
      <Stack gap={3}>
        <Row gap={3} align="end" class="flex-wrap">
          <div class="min-w-0 flex-1">
            <PathInput
              label="Directory"
              placeholder="/path/to/models"
              value={value()}
              onChange={setValue}
              disabled={dir.loading}
              onBrowse={
                picker() &&
                (() =>
                  picker()!({ mode: "directory", title: "Models directory" }))
              }
            />
          </div>
          <Button leading="check" disabled={!canSave()} onClick={save}>
            {saving() ? "Saving…" : "Save"}
          </Button>
        </Row>
        <Text variant="micro" tone="dim">
          Applies to new downloads — existing models stay where they are.
        </Text>
      </Stack>
    </Panel>
  );
}
