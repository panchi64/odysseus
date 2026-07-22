/** Global model state — the endpoint catalog, runtime model discovery, and the
 *  chat (`main`) model selection. One place owns all of it so the app shell's
 *  top-bar picker, the overview launchpad, chat, and Settings share a single
 *  source of truth (and a single `/models/endpoints` fetch).
 *
 *  An *endpoint* is a provider connection; its models are discovered at runtime
 *  from the provider (`GET /models/endpoints/{id}/models`). The chat model *is* the
 *  backend `main` role binding: the picker reads it from `/models/roles` and writes
 *  it back with `PUT /models/roles/main` (single endpoint + pinned model), so the
 *  same fact every server-initiated consumer resolves (research, tasks, titling) is
 *  the one the operator picked — no device-local authoritative state. The selection
 *  is held structured (`{endpointId, model}`); the `endpointId::model` composite
 *  exists only at the picker boundary (the Combobox needs one string per option),
 *  so a model id containing `::` never round-trips. The Settings ROLE BINDINGS panel
 *  writes the same binding — one source, two UIs. */

import {
  createComputed,
  createMemo,
  createResource,
  createRoot,
  createSignal,
  type Resource,
} from "solid-js";
import { api } from "~/lib/api";
import { useSession } from "~/lib/stores/session";

/** A specific model on a specific endpoint — the unit of selection. */
export interface ModelSelection {
  endpointId: string;
  model: string;
}

/** The verdict of the last reachability probe (null until first tested). The
 *  backend owns these tokens; the frontend renders them, never re-categorizes. */
export type EndpointStatus = "ok" | "error" | "untested";
export type EndpointErrorCategory =
  | "ok"
  | "auth"
  | "rate_limited"
  | "timeout"
  | "unreachable"
  | "bad_response"
  | "server_error";

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
  /** Whether this endpoint is active — disabled endpoints are hidden from the
   *  picker and skipped in fallback chains (the backend enforces both). */
  enabled: boolean;
  /** The last probe verdict (null until first tested). */
  lastStatus: EndpointStatus | null;
  lastErrorCategory: EndpointErrorCategory | null;
  /** A plain-language sentence the backend authored — rendered verbatim. */
  lastErrorDetail: string | null;
  /** ISO-8601 timestamp of the last probe (null until first tested). */
  lastCheckedAt: string | null;
}

/** The result of probing one endpoint (also persisted server-side). */
export interface EndpointTestResult {
  status: "ok" | "error";
  errorCategory: EndpointErrorCategory;
  errorDetail: string;
  checkedAt: string;
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

/* ── The `main` binding (the backend source of truth) ──────────────────────── */

interface RoleViewDTO {
  endpoint_ids: string[];
  model: string | null;
}

/** The chat model = the backend `main` role binding's head endpoint + pinned
 *  model. `main` is single-endpoint (the picker overwrites the whole binding), so
 *  the head is the only endpoint; a binding with no pinned model or no endpoint is
 *  not yet a concrete pick (null) — the picker then displays the first available. */
async function fetchMainSelection(): Promise<ModelSelection | null> {
  const roles = await api.get<Record<string, RoleViewDTO>>("/models/roles");
  const main = roles.main;
  const endpointId = main?.endpoint_ids?.[0];
  return endpointId && main.model ? { endpointId, model: main.model } : null;
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
  enabled: boolean;
  last_status: EndpointStatus | null;
  last_error_category: EndpointErrorCategory | null;
  last_error_detail: string | null;
  last_checked_at: string | null;
}
interface EndpointTestDTO {
  status: "ok" | "error";
  error_category: EndpointErrorCategory;
  error_detail: string;
  checked_at: string;
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
    enabled: dto.enabled,
    lastStatus: dto.last_status,
    lastErrorCategory: dto.last_error_category,
    lastErrorDetail: dto.last_error_detail,
    lastCheckedAt: dto.last_checked_at,
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

/** Discover the models one endpoint's provider serves (`GET …/{id}/models`).
 *  The single owner of that call — discovery and the guided connect flow both go
 *  through it. `supported` distinguishes a working-but-empty models API from one
 *  that couldn't be reached; on any failure it reads as unsupported + empty. */
export async function fetchEndpointModels(
  id: string,
): Promise<EndpointModelsDTO> {
  try {
    return await api.get<EndpointModelsDTO>(`/models/endpoints/${id}/models`, {
      signal: AbortSignal.timeout(DISCOVERY_TIMEOUT_MS),
    });
  } catch {
    return { models: [], supported: false };
  }
}

async function fetchDiscovery(
  endpoints: ModelEndpoint[],
): Promise<EndpointResult[]> {
  return Promise.all(
    endpoints.map(async (e): Promise<EndpointResult> => {
      const res = await fetchEndpointModels(e.id);
      let models = res.models;
      const supported = res.supported;
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

  // The chat model is the backend `main` role binding — the single source of
  // truth. `selection` is the local echo: seeded/reconciled from the binding and
  // moved optimistically by a pick (which writes the binding back).
  const [selection, setSelection] = createSignal<ModelSelection | null>(null);
  const [rolesTick, setRolesTick] = createSignal(1);
  const [mainBinding] = createResource(
    () => (session.isAuthenticated ? rolesTick() : false),
    fetchMainSelection,
  );
  // Reconcile the echo with the backend binding whenever it (re)loads — on first
  // unlock, after our own optimistic write, and after a Settings edit refreshes it.
  // Only on `ready` (not mid-refetch), so an in-flight optimistic pick isn't clobbered.
  createComputed(() => {
    if (mainBinding.state === "ready") setSelection(mainBinding.latest ?? null);
  });

  // The endpoint catalog — gated on unlock (a pre-auth call would 401); the tick
  // lets a write (create/update/delete) force a re-read, which cascades to
  // discovery since discovery's source is the endpoints list.
  const [endpointsTick, setEndpointsTick] = createSignal(1);
  const [endpoints] = createResource(
    () => (session.isAuthenticated ? endpointsTick() : false),
    fetchEndpoints,
  );

  // Disabled endpoints are excluded at the picker's source: discovery only runs
  // over live endpoints, so `groups`/`choices`/`pickerGroups` never offer one and
  // `effective()` auto-falls to the next live choice. (Settings reads the full
  // catalog directly off `endpoints` to still show disabled rows.)
  // Discovery's source is the *discovery-relevant* projection of the live
  // endpoints — id + model + baseUrl + whether a key is set. A health-only
  // refresh (last_status/last_error_*/last_checked_at change after a probe or a
  // toggle on another endpoint) must NOT re-trigger the per-endpoint /models
  // fetch for every endpoint, so the memo keeps its identity when only those
  // fields moved. Membership still changes when `enabled` flips (the picker must
  // update), so that re-fires discovery as intended.
  const liveEndpoints = createMemo<ModelEndpoint[] | false>(
    () => {
      const all = endpoints.latest;
      return all ? all.filter((e) => e.enabled) : false;
    },
    false,
    {
      equals: (prev, next) => {
        if (prev === false || next === false) return prev === next;
        if (prev.length !== next.length) return false;
        return prev.every((a, i) => {
          const b = next[i];
          return (
            a.id === b.id &&
            a.model === b.model &&
            a.baseUrl === b.baseUrl &&
            a.hasApiKey === b.hasApiKey
          );
        });
      },
    },
  );
  const [discovery] = createResource(
    () => (session.isAuthenticated ? liveEndpoints() : false),
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
    refreshRoles: () => setRolesTick((t) => t + 1),
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

/** Persist the chat model by writing the backend `main` binding (single endpoint +
 *  pinned model), moving the local echo optimistically and reconciling from the
 *  backend after — rolling the echo back if the write fails. `main` is
 *  single-endpoint, so this overwrites the whole binding. A null pick is a no-op
 *  write (the picker never clears the binding). */
export async function setSelectedModel(
  sel: ModelSelection | null,
): Promise<void> {
  if (!sel) return;
  const previous = store.selection();
  store.setSelection(sel); // optimistic
  try {
    await api.put("/models/roles/main", {
      endpoint_ids: [sel.endpointId],
      model: sel.model,
    });
    store.refreshRoles(); // reconcile with the persisted binding
  } catch (e) {
    store.setSelection(previous); // rollback
    store.refreshRoles();
    throw e;
  }
}

/** Combobox onChange adapter: decode the option value into a structured pick.
 *  Fire-and-forget — the optimistic echo (and its rollback on failure) is the UX. */
export function selectModelByValue(value: string): void {
  void setSelectedModel(decodeValue(value)).catch((e) =>
    console.error("failed to persist model selection", e),
  );
}

/** Re-read the backend `main` binding into the picker — call after another surface
 *  (Settings ROLE BINDINGS) writes `main`, so the top-bar picker reflects it live. */
export function refreshMainSelection(): void {
  store.refreshRoles();
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

/** Probe an endpoint now. The backend persists the verdict, so we re-read the
 *  catalog afterwards to reflect the new `last_*` fields; the verdict is also
 *  returned so the caller can surface it immediately. */
export async function testEndpoint(id: string): Promise<EndpointTestResult> {
  const dto = await api.post<EndpointTestDTO>(
    `/models/endpoints/${id}/test`,
    {},
  );
  refreshEndpoints();
  return {
    status: dto.status,
    errorCategory: dto.error_category,
    errorDetail: dto.error_detail,
    checkedAt: dto.checked_at,
  };
}

/** Enable/disable an endpoint, then re-read the catalog (cascades to the picker,
 *  which excludes disabled endpoints at its source). */
export async function setEndpointEnabled(
  id: string,
  enabled: boolean,
): Promise<void> {
  await api.patch(`/models/endpoints/${id}`, { enabled });
  refreshEndpoints();
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
