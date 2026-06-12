/** Global model-selection state — the chat (`main`) model the operator picks
 *  from the top-bar dropdown, shared across the app shell, chat, and the overview
 *  launchpad so every surface stays in sync.
 *
 *  An *endpoint* is a provider connection; its models are discovered at runtime
 *  from the provider (`GET /models/endpoints/{id}/models`). A selection is a
 *  specific model on a specific endpoint, encoded as `endpointId::model` so it
 *  rides through a single string (the picker value and the localStorage value).
 *  The backend re-resolves and is the authority — this is a presentation echo. */

import { createResource, createSignal } from "solid-js";
import { api } from "~/lib/api";
import { readLS, writeLS } from "~/lib/storage";
import { useSession } from "~/lib/stores/session";

/** A model the operator can pick: one model served by one endpoint. */
export interface ModelChoice {
  /** Composite `endpointId::model` — the picker/localStorage value. */
  value: string;
  /** The model id as the provider names it (shown and sent). */
  model: string;
  endpointId: string;
}

/** A provider grouping for the picker: an endpoint and the models it serves. */
export interface ModelGroup {
  endpointId: string;
  endpointName: string;
  choices: ModelChoice[];
}

const SEP = "::";

export function encodeChoice(endpointId: string, model: string): string {
  return `${endpointId}${SEP}${model}`;
}

/** Split a composite selection back into its parts (null if malformed/empty). */
export function parseSelection(
  value: string,
): { endpointId: string; model: string } | null {
  const i = value.indexOf(SEP);
  if (i < 0) return null;
  const endpointId = value.slice(0, i);
  const model = value.slice(i + SEP.length);
  return endpointId && model ? { endpointId, model } : null;
}

/* ── Sticky selection ───────────────────────────────────────────────────────── */

const MODEL_KEY = "ody.chat.model";
const [_selected, _setSelected] = createSignal<string>(readLS(MODEL_KEY) ?? "");

/** The operator's explicit pick (composite, or "" before they've chosen). Prefer
 *  `effectiveValue()` for display and `effectiveSelection()` for sending. */
export const selectedModel = _selected;

export function setSelectedModel(value: string): void {
  _setSelected(value);
  writeLS(MODEL_KEY, value);
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

async function fetchModelGroups(): Promise<ModelGroup[]> {
  let endpoints: EndpointDTO[];
  try {
    endpoints = await api.get<EndpointDTO[]>("/models/endpoints");
  } catch {
    return [];
  }
  const groups = await Promise.all(
    endpoints.map(async (e): Promise<ModelGroup> => {
      let models: string[] = [];
      try {
        const res = await api.get<EndpointModelsDTO>(
          `/models/endpoints/${e.id}/models`,
        );
        models = res.models;
      } catch {
        models = [];
      }
      // Always keep the configured default selectable — discovery may be
      // unavailable, or return a live list that omits a model the operator set
      // as the fallback. Lead with it so it stays the default pick.
      if (e.model && !models.includes(e.model)) models = [e.model, ...models];
      return {
        endpointId: e.id,
        endpointName: e.name,
        choices: models.map((m) => ({
          value: encodeChoice(e.id, m),
          model: m,
          endpointId: e.id,
        })),
      };
    }),
  );
  // Drop endpoints with nothing to offer (no discovery, no configured model).
  return groups.filter((g) => g.choices.length > 0);
}

// Mirrors the chat-session pattern: the source stays falsy until the operator
// unlocks, so no `/models/*` call fires pre-auth (it would 401); it re-fetches
// when the session flips to unlocked, and `refreshModelOptions` bumps the tick.
const [_tick, _setTick] = createSignal(1);
const _session = useSession();
const [_groups] = createResource(
  () => (_session.isAuthenticated ? _tick() : false),
  fetchModelGroups,
);

export function modelGroups(): ModelGroup[] {
  return _groups.latest ?? [];
}

/** The discovered models shaped for a grouped picker (`~/ui` Combobox): one
 *  group per endpoint, each model an option. Shared by every picker surface. */
export function modelPickerGroups(): {
  label: string;
  options: { value: string; label: string }[];
}[] {
  return modelGroups().map((g) => ({
    label: g.endpointName,
    options: g.choices.map((c) => ({ value: c.value, label: c.model })),
  }));
}

/** Re-read endpoints and their model lists (after Settings adds/edits one). */
export function refreshModelOptions(): void {
  _setTick((t) => t + 1);
}

/* ── Effective selection ──────────────────────────────────────────────────────
   The picker always resolves to a concrete model when any is configured: the
   operator's explicit pick if still valid, otherwise the first available. This
   keeps the dropdown showing a real selection without persisting a default the
   operator never made. */

function allChoices(): ModelChoice[] {
  return modelGroups().flatMap((g) => g.choices);
}

export function effectiveSelection(): {
  endpointId: string;
  model: string;
} | null {
  const choices = allChoices();
  const explicit = choices.find((c) => c.value === selectedModel());
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
