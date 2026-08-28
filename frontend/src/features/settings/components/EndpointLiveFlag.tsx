import { Show, type JSX } from "solid-js";
import { StatusFlag } from "~/ui";
import type { ModelEndpoint } from "~/lib/stores/models";

/** A managed engine's process liveness, rendered from `liveStatus` and never
 *  inferred from `enabled` or the endpoint's name. Renders nothing for an
 *  external endpoint (which has no process to be live). Shared by the endpoint
 *  rows and the model cards so the two can't describe the same engine
 *  differently. */
export function EndpointLiveFlag(props: {
  endpoint: ModelEndpoint;
}): JSX.Element {
  const running = () => props.endpoint.liveStatus === "running";
  return (
    <Show when={props.endpoint.managed}>
      <StatusFlag status={running() ? "nominal" : "warn"}>
        {running() ? "Running" : "Stopped"}
      </StatusFlag>
    </Show>
  );
}
