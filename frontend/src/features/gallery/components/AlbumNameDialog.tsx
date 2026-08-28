import { createEffect, createSignal, type JSX } from "solid-js";
import { Button, Input, Modal } from "~/ui";

/** Name a gallery album — a small Modal + Input for a one-field action, used for
 *  both create and rename (mirrors the system's `confirm` gate / documents'
 *  rename dialog). Enter submits; Escape / backdrop cancels (handled by Modal). */
export function AlbumNameDialog(props: {
  open: boolean;
  title: string;
  submitLabel: string;
  /** Pre-filled value (the current name when renaming; empty when creating). */
  initialName?: string;
  onClose: () => void;
  onSubmit: (name: string) => void | Promise<void>;
}): JSX.Element {
  const [value, setValue] = createSignal(props.initialName ?? "");
  const [busy, setBusy] = createSignal(false);

  // Seed the field each time the dialog opens.
  createEffect(() => {
    if (props.open) setValue(props.initialName ?? "");
  });

  const trimmed = (): string => value().trim();

  async function submit(): Promise<void> {
    if (!trimmed() || busy()) return;
    setBusy(true);
    try {
      await props.onSubmit(trimmed());
      props.onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={props.open}
      onClose={props.onClose}
      title={props.title}
      footer={
        <>
          <Button variant="ghost" onClick={props.onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            leading="check"
            disabled={!trimmed() || busy()}
            onClick={() => void submit()}
          >
            {props.submitLabel}
          </Button>
        </>
      }
    >
      <Input
        label="Name"
        value={value()}
        autofocus
        invalid={!trimmed()}
        hint={!trimmed() ? "Name must not be empty" : undefined}
        onInput={(e) => setValue(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            void submit();
          }
        }}
      />
    </Modal>
  );
}
