import { createEffect, createMemo } from "solid-js";
import { toast } from "~/ui";
import { endpointDiscovery, type EndpointDiscovery } from "~/lib/stores/models";

/**
 * Per-endpoint model discovery, indexed for lookup, plus the one alarm it owns:
 * an endpoint that contributes no selectable model at all. Discovery is the only
 * thing that knows that, so it's the thing that says so.
 */
export function useEndpointDiscovery(): (
  id: string,
) => EndpointDiscovery | undefined {
  // Index once per change — O(1) per row instead of a linear scan in each of N.
  const byId = createMemo(() => {
    const m = new Map<string, EndpointDiscovery>();
    for (const d of endpointDiscovery()) m.set(d.endpointId, d);
    return m;
  });

  // Discovery failed and no default is set, so the operator isn't left guessing.
  // Once per endpoint while this surface is open.
  const toasted = new Set<string>();
  createEffect(() => {
    for (const d of endpointDiscovery()) {
      if (d.status !== "unavailable") {
        // Recovered (or never failed) — re-arm so a later regression re-toasts.
        toasted.delete(d.endpointId);
        continue;
      }
      if (toasted.has(d.endpointId)) continue;
      toasted.add(d.endpointId);
      // `supported` distinguishes a working-but-empty models API from one that
      // couldn't be reached, so the operator knows where to look.
      const reason = d.supported
        ? "the provider listed no models"
        : "its models API was unavailable";
      toast.error(
        `No models for "${d.endpointName}" — ${reason}. Set a default model or check the provider.`,
      );
    }
  });

  return (id) => byId().get(id);
}
