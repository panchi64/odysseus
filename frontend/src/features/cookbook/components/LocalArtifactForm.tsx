import { createSignal, Show, type JSX } from "solid-js";
import { Button, Input, PathInput, Row, Stack, Text, toast } from "~/ui";
import type { EngineKind } from "~/lib/api/models-types";
import { importLocalModel, type PathPicker } from "../serving";

/** What each engine loads, and therefore what the chooser should ask for. */
const SHAPE: Record<
  EngineKind,
  {
    mode: "file" | "directory";
    label: string;
    placeholder: string;
    note: string;
  }
> = {
  "llama.cpp": {
    mode: "file",
    label: "Model file",
    placeholder: "/path/to/model.gguf",
    note: "llama.cpp serves a single .gguf file.",
  },
  mlx: {
    mode: "directory",
    label: "Model folder",
    placeholder: "/path/to/mlx-community__Model-4bit",
    note: "MLX serves a snapshot folder — the one holding config.json and the safetensors weights.",
  },
};

/**
 * Point an engine at weights that are already on disk.
 *
 * The counterpart to downloading: a model fetched outside Odysseus (or kept on an
 * external drive) is served in place. Nothing is copied into the models directory, and
 * removing the entry later leaves the files untouched.
 *
 * Typing the path always works; BROWSE appears only when the host can open a native
 * chooser, because a browser can't produce an absolute path on its own — the backend,
 * which runs on the operator's machine, opens the dialog and returns what was chosen.
 */
export function LocalArtifactForm(props: {
  engine: EngineKind | null;
  /** Opens a native chooser, or undefined when this host has none. */
  picker: PathPicker | undefined;
  onImported: () => void;
}): JSX.Element {
  const [path, setPath] = createSignal("");
  const [name, setName] = createSignal("");
  const [busy, setBusy] = createSignal(false);

  const shape = () => (props.engine ? SHAPE[props.engine] : null);
  const canAdd = () =>
    !busy() && props.engine != null && path().trim().length > 0;

  async function add(): Promise<void> {
    const engine = props.engine;
    if (engine == null || !canAdd()) return;
    setBusy(true);
    try {
      const model = await importLocalModel({
        engine,
        path: path().trim(),
        workload: "chat",
        name: name().trim() || null,
      });
      toast.success(`Added ${model.hfRepo}`);
      setPath("");
      setName("");
      props.onImported();
    } catch (err) {
      // The backend validates the path and says what it expected — show that verbatim
      // rather than a generic failure the operator can't act on.
      toast.error(
        (err as { detail?: string })?.detail ?? "Couldn't add that model",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Show when={shape()}>
      {(s) => (
        <Stack gap={3}>
          <Text variant="micro" tone="dim">
            Already have the weights? {s().note} They stay where they are —
            nothing is copied, and removing the entry later leaves your files
            alone.
          </Text>
          <PathInput
            label={s().label}
            placeholder={s().placeholder}
            value={path()}
            onChange={setPath}
            disabled={busy()}
            onBrowse={
              props.picker &&
              (() =>
                props.picker!({
                  mode: s().mode,
                  title: s().label,
                  extensions: s().mode === "file" ? ["gguf"] : null,
                }))
            }
          />
          <Row gap={3} align="end" class="flex-wrap">
            <div class="min-w-0 flex-1">
              <Input
                label="Name (optional)"
                placeholder="Taken from the file or folder"
                value={name()}
                onInput={(e) => setName(e.currentTarget.value)}
                disabled={busy()}
              />
            </div>
            <Button
              leading="plus"
              disabled={!canAdd()}
              onClick={() => void add()}
            >
              {busy() ? "Adding…" : "Add"}
            </Button>
          </Row>
        </Stack>
      )}
    </Show>
  );
}
