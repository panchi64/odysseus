import { createResource, createSignal, type Resource } from "solid-js";
import { api } from "~/lib/api";
import { bytes } from "~/lib/format";
import type {
  HardwareInfo,
  ModelEntry,
  RunningServer,
  RemoteEndpoint,
} from "./model";
import { mockRemoteEndpoints } from "./mocks";

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

interface CapabilitiesDTO {
  tools: boolean;
  vision: boolean;
  thinking: boolean;
  embedding: boolean;
  image_gen: boolean;
}

interface CompatibleModelDTO {
  model_id: string;
  name: string;
  params_b: number | null;
  quant: string;
  size_bytes: number;
  est_runtime_bytes: number;
  suitability: "nominal" | "warn" | "alert";
  fits: boolean;
  capabilities: CapabilitiesDTO;
  quality_display: number | null;
  quality_metric: string | null;
  detail: string;
}

interface CompatibleModelsDTO {
  models: CompatibleModelDTO[];
  available: boolean;
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

function mapModel(r: CompatibleModelDTO): ModelEntry {
  return {
    id: r.model_id,
    name: r.name,
    params: r.params_b != null ? `${r.params_b}B` : "—",
    quant: r.quant,
    sizeBytes: r.size_bytes,
    suitability: r.suitability,
    // Download tracking lands with the download flow; the list is read-only.
    downloaded: false,
    capabilities: {
      tools: r.capabilities.tools,
      vision: r.capabilities.vision,
      reasoning: r.capabilities.thinking,
      embedding: r.capabilities.embedding,
      imageGen: r.capabilities.image_gen,
    },
    qualityValue: r.quality_display,
    qualityMetric: r.quality_metric,
    description: r.detail,
  };
}

async function fetchHardware(): Promise<HardwareInfo> {
  return mapHardware(
    await api.get<HardwareProfileDTO>("/models/cookbook/hardware"),
  );
}

// Bumped when the active quality source changes, so the compatible list re-ranks.
const [modelsTick, setModelsTick] = createSignal(0);

async function fetchModels(): Promise<ModelEntry[]> {
  const res = await api.get<CompatibleModelsDTO>("/models/cookbook/compatible");
  return res.models.map(mapModel);
}

// --- quality source (the "RANK BY" selector) -------------------------------

interface QualitySourceOptionDTO {
  id: string;
  label: string;
  requires_key: boolean;
  has_key: boolean;
}
interface QualitySourceStateDTO {
  active: string;
  options: QualitySourceOptionDTO[];
}

export interface QualitySourceOption {
  id: string;
  label: string;
  requiresKey: boolean;
  hasKey: boolean;
}
export interface QualitySourceState {
  active: string;
  options: QualitySourceOption[];
}

const [sourceTick, setSourceTick] = createSignal(0);

async function fetchQualitySource(): Promise<QualitySourceState> {
  const dto = await api.get<QualitySourceStateDTO>(
    "/models/cookbook/quality-source",
  );
  return {
    active: dto.active,
    options: dto.options.map((o) => ({
      id: o.id,
      label: o.label,
      requiresKey: o.requires_key,
      hasKey: o.has_key,
    })),
  };
}

export function useQualitySource(): Resource<QualitySourceState> {
  const [data] = createResource(sourceTick, fetchQualitySource);
  return data;
}

/** Switch the ranking source; the backend persists it and rebuilds the catalog, so we
 *  refresh both the selector state and the compatible list. */
export async function setQualitySource(source: string): Promise<void> {
  await api.put("/models/cookbook/quality-source", { source });
  setSourceTick((n) => n + 1);
  setModelsTick((n) => n + 1);
}

/** Search the full model catalog for a free-text query, scored against the host —
 *  for checking a specific model the operator heard about. */
export async function searchModels(query: string): Promise<ModelEntry[]> {
  const res = await api.get<CompatibleModelsDTO>(
    `/models/cookbook/search?q=${encodeURIComponent(query)}`,
  );
  return res.models.map(mapModel);
}

async function fetchServers(): Promise<RunningServer[]> {
  // Local serving isn't built yet (COOK-4) — the backend serves nothing, so there
  // are no running servers to report. Honest empty rather than a fabricated list.
  return [];
}

async function fetchRemoteEndpoints(): Promise<RemoteEndpoint[]> {
  return mockRemoteEndpoints;
}

export function useHardware(): Resource<HardwareInfo> {
  const [data] = createResource(fetchHardware);
  return data;
}

export function useCookbookModels(): Resource<ModelEntry[]> {
  const [data] = createResource(modelsTick, fetchModels);
  return data;
}

export function useRunningServers(): Resource<RunningServer[]> {
  const [data] = createResource(fetchServers);
  return data;
}

export function useRemoteEndpoints(): Resource<RemoteEndpoint[]> {
  const [data] = createResource(fetchRemoteEndpoints);
  return data;
}
