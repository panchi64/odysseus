import { createSignal, type JSX } from "solid-js";
import { Button, Input, Modal, Stack, toast } from "~/ui";
import { renameConversation } from "../data";

/**
 * Renaming the open thread.
 *
 * A controller-and-dialog pair rather than a bare component: the room needs to *open* it
 * from a menu item, and the draft title, the submit and the "renamed"/"couldn't rename"
 * outcome are the dialog's business, not the room's. `createRenameConversation` hands back
 * the opener and the element to place; nothing else about the modal reaches the caller.
 *
 * The dialog closes optimistically, before the request settles. A rename is a small,
 * recoverable act, and holding a modal open on the round-trip reads as the button not
 * having worked — the toast carries the outcome either way.
 */
export interface RenameConversation {
  /** Open the dialog, seeded with the thread's current title. */
  open: () => void;
  /** The dialog itself — place it once, anywhere in the room's tree. */
  element: JSX.Element;
}

export function createRenameConversation(source: {
  conversationId: () => string | null;
  currentTitle: () => string | undefined;
}): RenameConversation {
  const [isOpen, setIsOpen] = createSignal(false);
  const [value, setValue] = createSignal("");

  const submit = async () => {
    const id = source.conversationId();
    if (!id) return;
    const title = value().trim();
    if (!title) return;
    setIsOpen(false);
    try {
      await renameConversation(id, title);
      toast.success("Conversation renamed");
    } catch {
      toast.error("Unable to rename the conversation.");
    }
  };

  return {
    open: () => {
      setValue(source.currentTitle() ?? "");
      setIsOpen(true);
    },
    element: (
      <Modal
        open={isOpen()}
        onClose={() => setIsOpen(false)}
        title="Rename conversation"
      >
        <Stack gap={3}>
          <Input
            label="Title"
            value={value()}
            onInput={(e) => setValue(e.currentTarget.value)}
            placeholder="Conversation title"
          />
          <div class="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setIsOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={!value().trim()}
              onClick={submit}
            >
              Save
            </Button>
          </div>
        </Stack>
      </Modal>
    ),
  };
}
