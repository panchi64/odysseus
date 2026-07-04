import { createSignal, Show, type JSX } from "solid-js";
import { Button, Markdown, Textarea, toast } from "~/ui";
import type { ViewDocumentRef } from "../model";

/**
 * Renders a document version's **preview** — its markdown + LaTeX body via the shared
 * `Markdown` component. The latest committed version is editable inline: an EDIT toggle
 * swaps the rendered prose for a `Textarea` seeded from the body; SAVE relays the new
 * body to the backend (which stamps origin=user and mints a new version) and CANCEL
 * restores. Only the latest committed version is editable — an older version or a
 * still-streaming body shows read-only. The frontend only renders + relays; the backend
 * owns the version it mints.
 */
export function ViewDocumentContent(props: {
  document: ViewDocumentRef;
  /** True only for the latest committed version — gates the inline editor. */
  editable: boolean;
  onSave: (documentId: string, body: string) => Promise<void>;
}): JSX.Element {
  const [editing, setEditing] = createSignal(false);
  const [draft, setDraft] = createSignal("");
  const [saving, setSaving] = createSignal(false);

  const startEdit = (): void => {
    setDraft(props.document.body);
    setEditing(true);
  };
  const cancel = (): void => {
    setEditing(false);
  };
  const save = async (): Promise<void> => {
    setSaving(true);
    try {
      await props.onSave(props.document.documentId, draft());
      toast.success("Document saved");
      setEditing(false);
    } catch (err) {
      toast.error(
        (err as { detail?: string })?.detail ?? "Unable to save the document.",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div class="flex h-full min-h-0 flex-col">
      <Show when={props.editable}>
        <div class="flex items-center justify-end gap-2 border-b border-line px-3 py-2">
          <Show
            when={editing()}
            fallback={
              <Button
                variant="ghost"
                size="sm"
                leading="edit"
                onClick={startEdit}
              >
                EDIT
              </Button>
            }
          >
            <Button
              variant="ghost"
              size="sm"
              onClick={cancel}
              disabled={saving()}
            >
              CANCEL
            </Button>
            <Button
              variant="primary"
              size="sm"
              leading="check"
              onClick={() => void save()}
              disabled={saving()}
            >
              SAVE
            </Button>
          </Show>
        </div>
      </Show>
      <div class="min-h-0 flex-1 overflow-auto p-3">
        <Show
          when={editing()}
          fallback={<Markdown>{props.document.body}</Markdown>}
        >
          <Textarea
            rows={24}
            aria-label="Edit document body"
            value={draft()}
            onInput={(e) => setDraft(e.currentTarget.value)}
          />
        </Show>
      </div>
    </div>
  );
}
