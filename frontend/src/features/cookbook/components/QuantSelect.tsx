import {
  createEffect,
  createResource,
  createSignal,
  onCleanup,
  Show,
  type JSX,
} from "solid-js";
import { Select } from "~/ui";
import type { EngineKind } from "../model";
import { fetchRepoQuants } from "../serving";

const DEBOUNCE_MS = 450;

/** Quant picker populated from the chosen repo's actual GGUF files. Only meaningful for
 *  llama.cpp (MLX bakes the quant into the repo id) and only once a repo id is entered —
 *  so it renders nothing otherwise, and nothing when the repo exposes no quants. The empty
 *  value is "Auto": let the engine pick its default GGUF, so accepting it stays one tap.
 *  Controlled — the parent owns the value so it flows straight into the serve call.
 *
 *  Visibility tracks the *current* engine + repo (`applies`), not the fetched list, because
 *  Solid retains a resource's last value after its source goes null; keying off the list
 *  alone would leave the dropdown on screen after switching to MLX or clearing the repo.
 *  The backend introspects the repo (the frontend never parses HF); the lookup is debounced
 *  so typing doesn't hit the hub on every keystroke. */
export function QuantSelect(props: {
  repo: string;
  engine: EngineKind | null;
  value: string;
  onChange: (value: string) => void;
}): JSX.Element {
  const [debouncedRepo, setDebouncedRepo] = createSignal("");

  // Debounce the repo so a fetch fires once typing settles, not on every keystroke.
  createEffect(() => {
    const repo = props.repo.trim();
    const timer = setTimeout(() => setDebouncedRepo(repo), DEBOUNCE_MS);
    onCleanup(() => clearTimeout(timer));
  });

  // A quant choice is applicable only for llama.cpp with a repo-id-shaped value (`org/name`).
  // Derived from the live props so switching engine or clearing the repo hides the control
  // immediately, regardless of any list still held by the resource.
  const applies = () =>
    props.engine === "llama.cpp" && /\S\/\S/.test(props.repo);

  const source = () =>
    applies() && /\S\/\S/.test(debouncedRepo())
      ? ({ repo: debouncedRepo() } as const)
      : null;

  const [quants] = createResource(source, (s) =>
    fetchRepoQuants(s.repo, "llama.cpp"),
  );

  // We're "reading" while the debounce hasn't caught up to the typed repo, or a fetch is in
  // flight — so the displayed options never describe a different repo than the current one.
  const reading = () =>
    applies() && (quants.loading || props.repo.trim() !== debouncedRepo());
  const ready = () =>
    applies() && !reading() && (quants.latest?.length ?? 0) > 0;

  // Clear a pick that no longer applies (engine left llama.cpp / repo cleared / changed) or
  // that the current repo doesn't offer, so a stale quant never reaches the serve call.
  createEffect(() => {
    if (!applies()) {
      if (props.value) props.onChange("");
      return;
    }
    const list = quants.latest;
    if (!reading() && list && props.value && !list.includes(props.value)) {
      props.onChange("");
    }
  });

  return (
    <Show when={reading() || ready()}>
      <Select
        label="QUANT"
        class="w-40 shrink-0"
        disabled={reading()}
        placeholder={reading() ? "READING…" : "Auto"}
        value={props.value}
        onChange={props.onChange}
        options={
          ready()
            ? [
                { value: "", label: "Auto" },
                ...(quants.latest ?? []).map((q) => ({ value: q, label: q })),
              ]
            : []
        }
      />
    </Show>
  );
}
