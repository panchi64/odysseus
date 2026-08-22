import { createResource, type Resource } from "solid-js";
import { api, isApiError } from "~/lib/api";
import { bytes } from "~/lib/format";
import {
  fetchEndpointModels,
  refreshEndpoints,
  setSelectedModel,
  testEndpoint,
  useEndpoints,
  type ModelEndpoint,
} from "~/lib/stores/models";
import { toast } from "~/ui";
// The canonical endpoint writers (own the POST/PATCH + body mapping) — reused,
// not re-implemented, so there is one create/update path.
import {
  createEndpoint as createEndpointWrite,
  updateEndpoint as updateEndpointWrite,
} from "~/features/settings/data";
import type { EndpointInput } from "~/features/settings/model";
import { modelsPageAction } from "./chatModelNotice";
import type { GuidedConnectInput, HardwareInfo } from "./model";

// --- backend DTOs (snake_case) — mapped to model.ts types below ------------

interface AcceleratorDTO {
  name: string;
  kind: string;
  vram_bytes: number | null;
  unified: boolean;
  gpu_cores: number | null;
}

interface HardwareProfileDTO {
  cpu: {
    model: string | null;
    physical_cores: number | null;
    logical_cores: number | null;
  };
  memory: { total_bytes: number | null; available_bytes: number | null };
  accelerators: AcceleratorDTO[];
  compute_backend: "metal" | "cuda" | "rocm" | "cpu";
  platform: { system: string; release: string; arch: string };
  runtimes: { name: string; version: string | null; available: boolean }[];
}

const BACKEND_LABEL: Record<string, string> = {
  metal: "Metal / MPS",
  cuda: "CUDA",
  rocm: "ROCm",
  cpu: "CPU",
};

function mapHardware(p: HardwareProfileDTO): HardwareInfo {
  const accel = p.accelerators[0];
  const cpuCores = p.cpu.physical_cores;
  const gpuCores = accel?.gpu_cores ?? null;
  const cores =
    cpuCores != null
      ? gpuCores != null
        ? `${cpuCores}C / ${gpuCores}GPU`
        : `${cpuCores}C`
      : "—";
  return {
    chip: p.cpu.model ?? accel?.name ?? "Unknown",
    ram: p.memory.total_bytes ? bytes(p.memory.total_bytes) : "—",
    vram: accel?.vram_bytes ? bytes(accel.vram_bytes) : "—",
    cores,
    backend:
      BACKEND_LABEL[p.compute_backend] ?? p.compute_backend.toUpperCase(),
    runtimes: p.runtimes
      .filter((r) => r.available)
      .map((r) => ({ name: r.name, version: r.version })),
  };
}

async function fetchHardware(): Promise<HardwareInfo> {
  return mapHardware(
    await api.get<HardwareProfileDTO>("/models/cookbook/hardware"),
  );
}

/** One host profile, fetched once and shared. The cookbook chrome and the LOCAL
 *  MODELS readout both want it, and the host's hardware doesn't change under us —
 *  a per-caller resource would just probe twice. */
let hardwareResource: Resource<HardwareInfo> | undefined;

export function useHardware(): Resource<HardwareInfo> {
  if (!hardwareResource) {
    const [data] = createResource(fetchHardware);
    hardwareResource = data;
  }
  return hardwareResource;
}

/** The configured endpoints, read from the shared models store — the same single
 *  `/models/endpoints` fetch the top-bar picker and Settings share. No second
 *  source of truth; the guided tab just renders what already-connected providers
 *  exist. */
export function useRemoteEndpoints(): Resource<ModelEndpoint[]> {
  return useEndpoints();
}

/** The guided "Connect & use this" flow: create the endpoint from a backend
 *  provider preset + pasted key, then **prove it works** (the backend test verdict
 *  — never the 201-create), then auto-select a sensible default model so the
 *  operator never has to pick. On failure the endpoint is left created so they can
 *  fix the key and retest from Settings. Returns true on a working connection.
 *
 *  This composes presentation-layer seams only; the backend re-resolves the
 *  selection at send time — the model pick here is an optimistic echo. */
export async function connectAndSelectEndpoint(
  input: GuidedConnectInput,
  /** Navigation for the acknowledgement toast's MODELS link. Supplied by the
   *  calling screen (this module has no router of its own); omitted ⇒ the toast
   *  still names the change, it just can't offer the jump. */
  navigate?: (href: string) => void,
): Promise<boolean> {
  const { provider, baseUrl, apiKey } = input;
  // The single preset→endpoint field mapping: the provider's preset seeds the
  // capability defaults; the backend owns everything it doesn't say.
  const body: EndpointInput = {
    name: provider.displayName,
    baseUrl,
    provider: provider.id,
    apiKey: apiKey || undefined,
    contextWindow: null,
    nativeTools: provider.nativeTools,
    vision: provider.vision,
    thinking: false,
  };

  // The backend enforces a unique (owner_id, name); the flow always uses the
  // provider's display name. So reuse an existing same-named endpoint (a prior
  // attempt that tested badly, or a pre-existing one) by UPDATING it instead of
  // re-POSTing the same name — that would 500. Retry-after-bad-key then just works.
  const existing = (useEndpoints().latest ?? []).find(
    (e) => e.name === provider.displayName,
  );
  let endpointId: string;
  try {
    if (existing) {
      await updateEndpointWrite(existing.id, body);
      endpointId = existing.id;
    } else {
      endpointId = await createEndpointWrite(body);
    }
  } catch (e) {
    // A 422 (e.g. a key-requiring provider without a key) carries a
    // plain-language detail from the backend — render it verbatim.
    toast.error(isApiError(e) ? e.detail : "Unable to create the connection.");
    return false;
  }

  // Success is the backend's reachability verdict, not the create/update.
  let verdict;
  try {
    verdict = await testEndpoint(endpointId);
  } catch {
    // The endpoint exists but the probe never landed — refresh so it appears in
    // the Connected Providers list (the operator retests it from there/Settings).
    refreshEndpoints();
    toast.error(
      `Created "${provider.displayName}", but the connection test failed.`,
    );
    return false;
  }

  if (verdict.status !== "ok") {
    // Leave the endpoint created — the operator fixes the key / retests in
    // Settings. testEndpoint already refreshed the catalog with the persisted
    // verdict, so the row reflects the failure.
    toast.error(verdict.errorDetail);
    return false;
  }

  // Pick a default model without making the operator choose: the provider's
  // live discovered list leads (the backend presets carry no model hints).
  const discovered = await fetchEndpointModels(endpointId);
  const model = discovered.models[0];

  if (model) {
    void setSelectedModel({ endpointId, model });
    // This picks the chat model on the operator's behalf, so say so in those
    // words and point at the page that owns the choice — the convenience is only
    // a convenience if it's visible and reversible.
    toast.success(
      `Connected "${provider.displayName}" — chat model set to ${model}.`,
      navigate ? { action: modelsPageAction(navigate) } : undefined,
    );
  } else {
    // Connected, but nothing is selectable: the provider advertised no models —
    // so don't point the operator at an empty top bar. `supported` tells whether
    // the model list could even be read.
    const note = discovered.supported
      ? ""
      : " (its model list couldn't be read)";
    toast.success(
      `Connected "${provider.displayName}", but it isn't serving any models yet${note} — ` +
        `start one on the provider, or set a model in Settings.`,
    );
  }

  // Re-read the catalog ONCE, now that the endpoint is tested + selected, so the
  // Connected Providers list and the picker reflect the final state (testEndpoint
  // and fetchEndpointModels work by id and didn't need it refreshed first).
  refreshEndpoints();
  return true;
}
