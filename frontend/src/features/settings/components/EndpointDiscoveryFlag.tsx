import { type JSX } from "solid-js";
import { StatusFlag } from "~/ui";
import type { EndpointDiscovery } from "~/lib/stores/models";

/** How many models an endpoint actually contributes: a live list, only its
 *  configured default, or nothing usable. Sibling of `EndpointHealthFlag` — the
 *  probe says whether the endpoint answers, this says whether it's any use. */
export function EndpointDiscoveryFlag(props: {
  discovery: EndpointDiscovery;
}): JSX.Element {
  const status = (): "nominal" | "warn" | "alert" => {
    if (props.discovery.status === "live") return "nominal";
    if (props.discovery.status === "default-only") return "warn";
    return "alert";
  };
  const label = (): string => {
    const { status: s, discovered } = props.discovery;
    if (s === "live")
      return `${discovered} ${discovered === 1 ? "MODEL" : "MODELS"}`;
    if (s === "default-only") return "DEFAULT ONLY";
    return "NO MODELS";
  };
  return <StatusFlag status={status()}>{label()}</StatusFlag>;
}
