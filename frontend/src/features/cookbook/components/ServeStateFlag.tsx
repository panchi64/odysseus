import { type JSX } from "solid-js";
import { StatusFlag, type Status } from "~/ui";
import type { ServeState } from "../model";

/** Lifecycle state → status accent. One place for the mapping so every surface
 *  that shows a managed model reads the same colors. */
const STATE_STATUS: Record<ServeState, Status> = {
  downloading: "info",
  starting: "info",
  running: "nominal",
  stopped: "idle",
  error: "alert",
};

/** The status flag for a managed model's lifecycle state — encapsulates the
 *  state→accent mapping, the downloading pulse, and the uppercased label, shared
 *  by the LOCAL MODELS rows and the GET STARTED local-serve flow. */
export function ServeStateFlag(props: { state: ServeState }): JSX.Element {
  return (
    <StatusFlag
      status={STATE_STATUS[props.state]}
      dot
      pulse={props.state === "downloading"}
    >
      {props.state.toUpperCase()}
    </StatusFlag>
  );
}
