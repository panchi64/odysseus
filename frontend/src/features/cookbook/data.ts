import { createResource, type Resource } from "solid-js";
import { api } from "~/lib/api";
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
import { presetToEndpointInput } from "./presets";
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

export function useHardware(): Resource<HardwareInfo> {
  const [data] = createResource(fetchHardware);
  return data;
}

/** The configured endpoints, read from the shared models store — the same single
 *  `/models/endpoints` fetch the top-bar picker and Settings share. No second
 *  source of truth; the guided tab just renders what already-connected providers
 *  exist. */
export function useRemoteEndpoints(): Resource<ModelEndpoint[]> {
  return useEndpoints();
}

/** The guided "Connect & use this" flow: create the endpoint from a preset +
 *  pasted key, then **prove it works** (the backend test verdict — never the
 *  201-create), then auto-select a sensible default model so the operator never
 *  has to pick. On failure the endpoint is left created so they can fix the key
 *  and retest from Settings. Returns true on a working connection.
 *
 *  This composes presentation-layer seams only; the backend re-resolves the
 *  selection at send time — the model pick here is an optimistic echo. */
export async function connectAndSelectEndpoint(
  input: GuidedConnectInput,
): Promise<boolean> {
  const { preset, apiKey } = input;
  const body = presetToEndpointInput(preset, apiKey);

  // The backend enforces a unique (owner_id, name); the flow always uses the
  // preset's name. So reuse an existing same-named endpoint (a prior attempt that
  // tested badly, or a pre-existing one) by UPDATING it instead of re-POSTing the
  // same name — that would 500. Retry-after-bad-key then just works.
  const existing = (useEndpoints().latest ?? []).find(
    (e) => e.name === preset.name,
  );
  let endpointId: string;
  try {
    if (existing) {
      await updateEndpointWrite(existing.id, body);
      endpointId = existing.id;
    } else {
      endpointId = await createEndpointWrite(body);
    }
  } catch {
    toast.error("Unable to create the connection.");
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
    toast.error(`Created "${preset.name}", but the connection test failed.`);
    return false;
  }

  if (verdict.status !== "ok") {
    // Leave the endpoint created — the operator fixes the key / retests in
    // Settings. testEndpoint already refreshed the catalog with the persisted
    // verdict, so the row reflects the failure.
    toast.error(verdict.errorDetail);
    return false;
  }

  // Pick a default model without making the operator choose: prefer the
  // provider's live discovered list (so a stale preset hint self-heals), and only
  // fall back to the preset hint / configured default when discovery is empty.
  const discovered = await fetchEndpointModels(endpointId);
  const model =
    discovered.models.length > 0
      ? preset.suggestedModel &&
        discovered.models.includes(preset.suggestedModel)
        ? preset.suggestedModel
        : discovered.models[0]
      : preset.suggestedModel;

  if (model) {
    setSelectedModel({ endpointId, model });
    toast.success(`Connected "${preset.name}" — using ${model}.`);
  } else {
    // Connected, but nothing is selectable: the provider advertised no models and
    // the preset gave no hint — so don't point the operator at an empty top bar.
    // `supported` tells whether the model list could even be read.
    const note = discovered.supported
      ? ""
      : " (its model list couldn't be read)";
    toast.success(
      `Connected "${preset.name}", but it isn't serving any models yet${note} — ` +
        `start one on the provider, or set a model in Settings.`,
    );
  }

  // Re-read the catalog ONCE, now that the endpoint is tested + selected, so the
  // Connected Providers list and the picker reflect the final state (testEndpoint
  // and fetchEndpointModels work by id and didn't need it refreshed first).
  refreshEndpoints();
  return true;
}
