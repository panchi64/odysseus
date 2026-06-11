import { Show, type JSX } from "solid-js";
import { apiUrl } from "~/lib/config";
import { Panel, StatusFlag, Text } from "~/ui";
import type { PreviewRef } from "../model";

/**
 * Mounts a live server the agent started in its sandbox. The backend reverse-
 * proxies it under a token-gated path on the API origin; the token *is* the
 * credential, so the iframe needs no auth header. Sandboxed without
 * `allow-same-origin` so the framed (model-generated) app runs in an opaque
 * origin and can't act as the operator against the API.
 */
export function PreviewPane(props: { preview: PreviewRef }): JSX.Element {
  return (
    <Panel
      label="LIVE PREVIEW"
      meta={
        <span class="flex items-center gap-2">
          <Show when={props.preview.title}>
            <Text variant="micro" tone="dim">
              {props.preview.title}
            </Text>
          </Show>
          <StatusFlag status="nominal" dot>
            LIVE
          </StatusFlag>
        </span>
      }
    >
      <iframe
        src={apiUrl(props.preview.url)}
        title={props.preview.title ?? "Live preview"}
        class="h-96 w-full border-0 bg-bright"
        sandbox="allow-scripts allow-forms allow-popups"
      />
    </Panel>
  );
}
