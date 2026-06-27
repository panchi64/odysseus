import { type JSX } from "solid-js";
import { Button, EmptyState, Panel } from "~/ui";

/** The chat workspace's viewport — the resizable pane where documents, live
 *  previews, and artifacts render beside the conversation instead of inline in
 *  the transcript. Deliberately empty for now: it establishes the side-by-side
 *  layout and the mount point so a later step can route the agent's
 *  `preview.ready` / `artifact.published` events here without reshaping the page.
 *  The frontend only renders what those events describe; it decides nothing. */
export function ViewportPanel(props: { onClose: () => void }): JSX.Element {
  return (
    <Panel
      label="VIEWPORT"
      meta={
        <Button
          variant="ghost"
          size="sm"
          leading="chevron-right"
          aria-label="Collapse viewport"
          onClick={() => props.onClose()}
        />
      }
      flush
      class="h-full"
    >
      <EmptyState
        icon="eye"
        message="NOTHING TO SHOW YET"
        hint="Documents, live previews, and artifacts from this conversation appear here."
      />
    </Panel>
  );
}
