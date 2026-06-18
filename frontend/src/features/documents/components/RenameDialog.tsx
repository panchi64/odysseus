import { createEffect, createSignal, type JSX } from "solid-js";
import { Button, Input, Modal } from "~/ui";

/** Rename a document. A small Modal + Input — the system's pattern for a
 *  consequential one-field action (mirrors `confirm`). Enter submits, Escape /
 *  backdrop cancels (handled by Modal). */
export function RenameDialog(props: {
  open: boolean;
  currentTitle: string;
  onClose: () => void;
  onSubmit: (title: string) => void | Promise<void>;
}): JSX.Element {
  const [value, setValue] = createSignal(props.currentTitle);
  const [busy, setBusy] = createSignal(false);

  // Seed the field each time the dialog opens (on whichever document).
  createEffect(() => {
    if (props.open) setValue(props.currentTitle);
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
      title="RENAME DOCUMENT"
      footer={
        <>
          <Button variant="ghost" onClick={props.onClose}>
            CANCEL
          </Button>
          <Button
            variant="primary"
            leading="check"
            disabled={!trimmed() || busy()}
            onClick={() => void submit()}
          >
            SAVE
          </Button>
        </>
      }
    >
      <Input
        label="TITLE"
        value={value()}
        autofocus
        invalid={!trimmed()}
        hint={!trimmed() ? "Title must not be empty" : undefined}
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
