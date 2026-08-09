import { createSignal, For, Show, type JSX } from "solid-js";
import {
  Button,
  EmptyState,
  HIDDEN_FILE_INPUT,
  ListRow,
  Panel,
  Text,
  confirm,
  toast,
  useFileDrop,
} from "~/ui";
import { bytes } from "~/lib/format";
import {
  deleteSkillFile,
  downloadSkillFile,
  putSkillFile,
  skillErrorMessage,
} from "../data";
import type { SkillFile } from "../model";

/** The bundle's supporting files — the part of an Agent Skills package that
 *  isn't `SKILL.md`. A file's path is its identity, so uploading one under an
 *  existing name replaces it. */
export function SkillBundlePanel(props: {
  skillId: string;
  files: SkillFile[];
}): JSX.Element {
  const [busy, setBusy] = createSignal(false);

  const picker = useFileDrop((files) => void addFiles(files));

  async function addFiles(files: File[]): Promise<void> {
    setBusy(true);
    try {
      // Sequential: each PUT returns the whole skill, so overlapping writes would
      // race on the file list the response carries.
      for (const file of files) {
        await putSkillFile(props.skillId, file.name, file);
      }
      toast.success(
        files.length > 1
          ? `Added ${files.length} files`
          : `Added ${files[0].name}`,
      );
    } catch (err) {
      toast.error(skillErrorMessage(err, "Could not add the file."));
    } finally {
      setBusy(false);
    }
  }

  async function remove(file: SkillFile): Promise<void> {
    const ok = await confirm({
      title: `Remove "${file.relpath}"?`,
      detail: "The file is deleted from this skill's bundle.",
      confirmLabel: "REMOVE",
      tone: "alert",
    });
    if (!ok) return;
    try {
      await deleteSkillFile(props.skillId, file.relpath);
      toast.success(`Removed ${file.relpath}`);
    } catch (err) {
      toast.error(skillErrorMessage(err, "Could not remove the file."));
    }
  }

  async function download(file: SkillFile): Promise<void> {
    try {
      await downloadSkillFile(props.skillId, file.relpath);
    } catch (err) {
      toast.error(skillErrorMessage(err, "Could not download the file."));
    }
  }

  return (
    <Panel
      label="BUNDLE FILES"
      flush
      meta={
        <Text variant="micro" tone="dim" class="tabular-nums">
          {props.files.length}
        </Text>
      }
    >
      <Show
        when={props.files.length}
        fallback={
          <EmptyState
            icon="file"
            message="NO FILES"
            hint="Scripts, templates, and references shipped with this skill appear here."
          />
        }
      >
        <For each={props.files}>
          {(file) => (
            <ListRow
              label={file.relpath}
              leading="file"
              right={
                <span class="flex shrink-0 items-center gap-2">
                  <Text variant="micro" tone="dim">
                    {bytes(file.sizeBytes)}
                  </Text>
                  <Button
                    variant="ghost"
                    size="sm"
                    leading="download"
                    onClick={() => void download(file)}
                  >
                    GET
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    leading="trash"
                    onClick={() => void remove(file)}
                  >
                    REMOVE
                  </Button>
                </span>
              }
            />
          )}
        </For>
      </Show>

      <div class="border-t border-line p-3">
        <input
          ref={picker.bindInput}
          {...HIDDEN_FILE_INPUT}
          {...picker.inputHandlers}
        />
        <Button
          variant="default"
          size="sm"
          leading="plus"
          block
          disabled={busy()}
          onClick={picker.openPicker}
        >
          {busy() ? "ADDING…" : "ADD FILE"}
        </Button>
      </div>
    </Panel>
  );
}
