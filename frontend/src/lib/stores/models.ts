/** Global model state — the endpoint catalog, runtime model discovery, and the
 *  chat (`main`) model selection. One place owns all of it so the app shell's
 *  top-bar picker, the overview launchpad, chat, and Settings share a single
 *  source of truth (and a single `/models/endpoints` fetch).
 *
 *  An *endpoint* is a provider connection; its models are discovered at runtime
 *  from the provider (`GET /models/endpoints/{id}/models`). The selection is held
 *  structured (`{endpointId, model}`) and JSON-persisted; the `endpointId::model`
 *  composite exists only at the picker boundary (the Combobox needs one string
 *  per option), so a model id containing `::` never round-trips through storage.
 *  The backend re-resolves and is the authority — this is a presentation echo. */

import {
  createMemo,
  createResource,
  createRoot,
  createSignal,
  type Resource,
} from "solid-js";
import { api } from "~/lib/api";
import { readLS, removeLS, writeLS } from "~/lib/storage";
import { useSession } from "~/lib/stores/session";

/** A specific model on a specific endpoint — the unit of selection. */
export interface ModelSelection {
  endpointId: string;
  model: string;
}

/** The operator's view of a configured endpoint (the shared read shape). */
export interface ModelEndpoint {
  id: string;
  name: string;
  baseUrl: string;
  /** Default/fallback model. Null when models are discovered dynamically and no
   *  default was set. */
  model: string | null;
  /** Whether a key is stored — the value is write-only and never returned. */
  hasApiKey: boolean;
  contextWindow: number | null;
  nativeTools: boolean;
  vision: boolean;
  thinking: boolean;
}

/** One model served by one endpoint, for the picker. */
export interface ModelChoice {
  model: string;
  endpointId: string;
}

/** A provider grouping for the picker: an endpoint and the models it serves. */
export interface ModelGroup {
  endpointId: string;
  endpointName: string;
  choices: ModelChoice[];
}

/** Whether an endpoint's models came from a live API, a configured default, or
 *  nothing at all — surfaced as a status badge in Settings. */
export type DiscoveryStatus = "live" | "default-only" | "unavailable";

export interface EndpointDiscovery {
  endpointId: string;
  endpointName: string;
  status: DiscoveryStatus;
  /** Count the provider's models API advertised (0 when unsupported/empty). */
  discovered: number;
  /** Whether the provider has a working models API. */
  supported: boolean;
}

/* ── Composite encoding (picker boundary only) ─────────────────────────────── */

const SEP = "::";

function encodeChoice(endpointId: string, model: string): string {
  return `${endpointId}${SEP}${model}`;
}

function decodeValue(value: string): ModelSelection | null {
  const i = value.indexOf(SEP);
  if (i < 0) return null;
  const endpointId = value.slice(0, i);
  const model = value.slice(i + SEP.length);
  return endpointId && model ? { endpointId, model } : null;
}

/* ── Sticky selection (structured, JSON-persisted) ─────────────────────────── */

const MODEL_KEY = "ody.chat.model";

function readSelection(): ModelSelection | null {
  const raw = readLS(MODEL_KEY);
  if (!raw) return null;
  try {
    const o = JSON.parse(raw) as Partial<ModelSelection>;
    return o.endpointId && o.model
      ? { endpointId: o.endpointId, model: o.model }
      : null;
  } catch {
    return null;
  }
}

/* ── Backend DTOs + mappers ────────────────────────────────────────────────── */

interface EndpointView {
  id: string;
  name: string;
  base_url: string;
  model: string | null;
  has_api_key: boolean;
  context_window: number | null;
  native_tools: boolean;
  vision: boolean;
  thinking: boolean;
}
interface EndpointModelsDTO {
  models: string[];
  supported: boolean;
}

/** The single snake_case→camel mapper for an endpoint row, shared by the picker
 *  and Settings so a backend rename is fixed in one place. */
export function toEndpoint(dto: EndpointView): ModelEndpoint {
  return {
    id: dto.id,
    name: dto.name,
    baseUrl: dto.base_url,
    model: dto.model,
    hasApiKey: dto.has_api_key,
    contextWindow: dto.context_window,
    nativeTools: dto.native_tools,
    vision: dto.vision,
    thinking: dto.thinking,
  };
}

interface EndpointResult {
  endpointId: string;
  endpointName: string;
  supported: boolean;
  discovered: number;
  choices: ModelChoice[];
}

// A slow/unreachable provider must not freeze the picker on the backend's
// longer budget — bound each discovery call independently of the server.
const DISCOVERY_TIMEOUT_MS = 3000;

async function fetchEndpoints(): Promise<ModelEndpoint[]> {
  const rows = await api.get<EndpointView[]>("/models/endpoints");
  return rows.map(toEndpoint);
}

async function fetchDiscovery(
  endpoints: ModelEndpoint[],
): Promise<EndpointResult[]> {
  return Promise.all(
    endpoints.map(async (e): Promise<EndpointResult> => {
      let models: string[] = [];
      let supported = false;
      try {
        const res = await api.get<EndpointModelsDTO>(
          `/models/endpoints/${e.id}/models`,
          { signal: AbortSignal.timeout(DISCOVERY_TIMEOUT_MS) },
        );
        models = res.models;
        supported = res.supported;
      } catch {
        /* unreachable / timeout → unsupported, fall back to the default */
      }
      const discovered = models.length;
      // Always keep the configured default selectable, leading the list.
      if (e.model && !models.includes(e.model)) models = [e.model, ...models];
      return {
        endpointId: e.id,
        endpointName: e.name,
        supported,
        discovered,
        choices: models.map((m) => ({ model: m, endpointId: e.id })),
      };
    }),
  );
}

function statusOf(r: EndpointResult): DiscoveryStatus {
  if (r.discovered > 0) return "live";
  return r.choices.length > 0 ? "default-only" : "unavailable";
}

/* ── The reactive store ─────────────────────────────────────────────────────────
   Owned by one app-lifetime root so the derivations can be memoized (computed
   once per change, shared across every surface) without dangling computations.
   The endpoints resource is the single `/models/endpoints` fetch; discovery is
   derived from it, so the catalog renders immediately and badges fill in. */

const store = createRoot(() => {
  const session = useSession();

  const [selection, setSelection] = createSignal<ModelSelection | null>(
    readSelection(),
  );

  // The endpoint catalog — gated on unlock (a pre-auth call would 401); the tick
  // lets a write (create/update/delete) force a re-read, which cascades to
  // discovery since discovery's source is the endpoints list.
  const [endpointsTick, setEndpointsTick] = createSignal(1);
  const [endpoints] = createResource(
    () => (session.isAuthenticated ? endpointsTick() : false),
    fetchEndpoints,
  );

  const [discovery] = createResource(
    () => (session.isAuthenticated ? (endpoints.latest ?? false) : false),
    fetchDiscovery,
  );

  const results = createMemo<EndpointResult[]>(() => discovery.latest ?? []);
  const groups = createMemo<ModelGroup[]>(() =>
    results()
      .filter((r) => r.choices.length > 0)
      .map((r) => ({
        endpointId: r.endpointId,
        endpointName: r.endpointName,
        choices: r.choices,
      })),
  );
  const choices = createMemo<ModelChoice[]>(() =>
    groups().flatMap((g) => g.choices),
  );
  const pickerGroups = createMemo(() =>
    groups().map((g) => ({
      label: g.endpointName,
      options: g.choices.map((c) => ({
        value: encodeChoice(c.endpointId, c.model),
        label: c.model,
      })),
    })),
  );
  const discoveries = createMemo<EndpointDiscovery[]>(() =>
    results().map((r) => ({
      endpointId: r.endpointId,
      endpointName: r.endpointName,
      discovered: r.discovered,
      supported: r.supported,
      status: statusOf(r),
    })),
  );
  // The picker always resolves to a concrete model when any is configured: the
  // operator's explicit pick if still valid, otherwise the first available.
  const effective = createMemo<ModelSelection | null>(() => {
    const all = choices();
    const sel = selection();
    const explicit =
      sel &&
      all.find((c) => c.endpointId === sel.endpointId && c.model === sel.model);
    if (explicit)
      return { endpointId: explicit.endpointId, model: explicit.model };
    const first = all[0];
    return first ? { endpointId: first.endpointId, model: first.model } : null;
  });
  // The endpoint backing the effective pick — the single source for its metadata
  // (provider name, context window) so consumers don't re-derive the lookup.
  const effectiveEndpoint = createMemo<ModelEndpoint | null>(() => {
    const sel = effective();
    if (!sel) return null;
    return (
      (endpoints.latest ?? []).find((e) => e.id === sel.endpointId) ?? null
    );
  });

  return {
    selection,
    setSelection,
    endpoints,
    setEndpointsTick,
    groups,
    pickerGroups,
    discoveries,
    effective,
    effectiveEndpoint,
  };
});

/* ── Public surface ─────────────────────────────────────────────────────────── */

/** The operator's explicit pick (or null before they've chosen). Prefer
 *  `effectiveValue()` for display and `effectiveSelection()` for sending. */
export const selectedModel = store.selection;

export function setSelectedModel(sel: ModelSelection | null): void {
  store.setSelection(sel);
  if (sel) writeLS(MODEL_KEY, JSON.stringify(sel));
  else removeLS(MODEL_KEY);
}

/** Combobox onChange adapter: decode the option value into a structured pick. */
export function selectModelByValue(value: string): void {
  setSelectedModel(decodeValue(value));
}

/** Encode a structured selection into the composite string the picker uses as a
 *  value. For surfaces that own a *local* model pick (e.g. each compare pane)
 *  rather than the global sticky selection. */
export function encodeModelValue(sel: ModelSelection): string {
  return encodeChoice(sel.endpointId, sel.model);
}

/** Decode a picker composite value back to a structured selection (null if
 *  malformed) — the read side of `encodeModelValue` for locally-owned picks. */
export function decodeModelValue(value: string): ModelSelection | null {
  return decodeValue(value);
}

/** The endpoint catalog resource — shared by the picker and Settings. */
export function useEndpoints(): Resource<ModelEndpoint[]> {
  return store.endpoints;
}

/** Re-read the catalog (after a create/update/delete); cascades to discovery. */
export function refreshEndpoints(): void {
  store.setEndpointsTick((t) => t + 1);
}

/** Endpoints with at least one selectable model, grouped for the picker. */
export function modelGroups(): ModelGroup[] {
  return store.groups();
}

/** The discovered models shaped for a grouped picker (`~/ui` Combobox). */
export function modelPickerGroups(): {
  label: string;
  options: { value: string; label: string }[];
}[] {
  return store.pickerGroups();
}

/** Per-endpoint discovery state for Settings (badges + failure surfacing). */
export function endpointDiscovery(): EndpointDiscovery[] {
  return store.discoveries();
}

export function effectiveSelection(): ModelSelection | null {
  return store.effective();
}

/** The composite value the picker should show as active (effective pick). */
export function effectiveValue(): string {
  const sel = store.effective();
  return sel ? encodeChoice(sel.endpointId, sel.model) : "";
}

/** The model id to display (or "" when nothing is configured). */
export function selectedModelLabel(): string {
  return store.effective()?.model ?? "";
}

/** The context window of the endpoint backing the effective pick (null when
 *  nothing is configured or the endpoint declares none). */
export function effectiveContextWindow(): number | null {
  return store.effectiveEndpoint()?.contextWindow ?? null;
}
