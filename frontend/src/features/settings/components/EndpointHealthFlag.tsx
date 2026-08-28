import { type JSX } from "solid-js";
import { StatusFlag } from "~/ui";
import type { EndpointStatus } from "~/lib/api/models-types";

/** The backend owns the verdict; this maps its `last_status` token to one of the
 *  design system's status accents for the health dot. No re-categorization — a
 *  token→accent presentation map. The one shared mapping so the Settings endpoint
 *  rows and the guided cookbook tab's CONNECTED PROVIDERS list never drift. */
export function healthStatus(
  s: EndpointStatus | null,
): "nominal" | "alert" | "idle" {
  if (s === "ok") return "nominal";
  if (s === "error") return "alert";
  return "idle"; // untested / null
}

function healthLabel(s: EndpointStatus | null): string {
  if (s === "ok") return "OK";
  if (s === "error") return "Error";
  return "Untested";
}

/** The endpoint health badge: a dotted StatusFlag rendering an endpoint's last
 *  probe verdict (ok → OK, error → ERROR, else → UNTESTED). */
export function EndpointHealthFlag(props: {
  status: EndpointStatus | null;
}): JSX.Element {
  return (
    <StatusFlag dot status={healthStatus(props.status)}>
      {healthLabel(props.status)}
    </StatusFlag>
  );
}
