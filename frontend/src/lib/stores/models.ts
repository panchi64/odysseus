/** Global model-selection state — the chat (`main`) model the operator picks
 *  from the top-bar dropdown, shared across the app shell, chat, and the overview
 *  launchpad so every surface stays in sync.
 *
 *  An *endpoint* is a provider connection; its models are discovered at runtime
 *  from the provider (`GET /models/endpoints/{id}/models`). The selection is held
 *  structured (`{endpointId, model}`) and JSON-persisted; the `endpointId::model`
 *  composite exists only at the picker boundary (the Combobox needs one string
 *  per option), so a model id containing `::` never round-trips through storage.
 *  The backend re-resolves and is the authority — this is a presentation echo. */

import { createResource, createSignal } from "solid-js";
import { api } from "~/lib/api";
import { readLS, removeLS, writeLS } from "~/lib/storage";
import { useSession } from "~/lib/stores/session";

/** A specific model on a specific endpoint — the unit of selection. */
export interface ModelSelection {
  endpointId: string;
  model: string;
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

const [_selected, _setSelected] = createSignal<ModelSelection | null>(
  readSelection(),
);

/** The operator's explicit pick (or null before they've chosen). Prefer
 *  `effectiveValue()` for display and `effectiveSelection()` for sending. */
export const selectedModel = _selected;

export function setSelectedModel(sel: ModelSelection | null): void {
  _setSelected(sel);
  if (sel) writeLS(MODEL_KEY, JSON.stringify(sel));
  else removeLS(MODEL_KEY);
}

/** Combobox onChange adapter: decode the option value into a structured pick. */
export function selectModelByValue(value: string): void {
  setSelectedModel(decodeValue(value));
}

/* ── Dynamic discovery ──────────────────────────────────────────────────────── */

interface EndpointDTO {
  id: string;
  name: string;
  model: string | null;
}
interface EndpointModelsDTO {
  models: string[];
  supported: boolean;
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

async function fetchEndpointResults(): Promise<EndpointResult[]> {
  let endpoints: EndpointDTO[];
  try {
    endpoints = await api.get<EndpointDTO[]>("/models/endpoints");
  } catch {
    return [];
  }
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

// Mirrors the chat-session pattern: the source stays falsy until the operator
// unlocks, so no `/models/*` call fires pre-auth (it would 401); it re-fetches
// when the session flips to unlocked, and `refreshModelOptions` bumps the tick.
const [_tick, _setTick] = createSignal(1);
const _session = useSession();
const [_results] = createResource(
  () => (_session.isAuthenticated ? _tick() : false),
  fetchEndpointResults,
);

function results(): EndpointResult[] {
  return _results.latest ?? [];
}

/** Re-read endpoints and their model lists (after Settings adds/edits one). */
export function refreshModelOptions(): void {
  _setTick((t) => t + 1);
}

/** Endpoints with at least one selectable model, grouped for the picker. */
export function modelGroups(): ModelGroup[] {
  return results()
    .filter((r) => r.choices.length > 0)
    .map((r) => ({
      endpointId: r.endpointId,
      endpointName: r.endpointName,
      choices: r.choices,
    }));
}

/** The discovered models shaped for a grouped picker (`~/ui` Combobox): one
 *  group per endpoint, each model an option. Shared by every picker surface. */
export function modelPickerGroups(): {
  label: string;
  options: { value: string; label: string }[];
}[] {
  return modelGroups().map((g) => ({
    label: g.endpointName,
    options: g.choices.map((c) => ({
      value: encodeChoice(c.endpointId, c.model),
      label: c.model,
    })),
  }));
}

/** Per-endpoint discovery state for Settings (badges + failure surfacing). */
export function endpointDiscovery(): EndpointDiscovery[] {
  return results().map((r) => ({
    endpointId: r.endpointId,
    endpointName: r.endpointName,
    discovered: r.discovered,
    supported: r.supported,
    status:
      r.discovered > 0
        ? "live"
        : r.choices.length > 0
          ? "default-only"
          : "unavailable",
  }));
}

/* ── Effective selection ──────────────────────────────────────────────────────
   The picker always resolves to a concrete model when any is configured: the
   operator's explicit pick if still valid, otherwise the first available. This
   keeps the dropdown showing a real selection without persisting a default the
   operator never made. */

function allChoices(): ModelChoice[] {
  return modelGroups().flatMap((g) => g.choices);
}

export function effectiveSelection(): ModelSelection | null {
  const choices = allChoices();
  const sel = selectedModel();
  const explicit =
    sel &&
    choices.find(
      (c) => c.endpointId === sel.endpointId && c.model === sel.model,
    );
  if (explicit)
    return { endpointId: explicit.endpointId, model: explicit.model };
  const first = choices[0];
  return first ? { endpointId: first.endpointId, model: first.model } : null;
}

/** The composite value the picker should show as active (effective pick). */
export function effectiveValue(): string {
  const sel = effectiveSelection();
  return sel ? encodeChoice(sel.endpointId, sel.model) : "";
}

/** The model id to display (or "" when nothing is configured). */
export function selectedModelLabel(): string {
  return effectiveSelection()?.model ?? "";
}
