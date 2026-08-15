import { createMemo, For, type JSX } from "solid-js";
import type { EngineKind } from "~/lib/api/models-types";
import type { EngineRecommendation } from "../model";
import { EngineRow } from "./EngineRow";

/** The engine chooser: every engine ranked for this host shown as a selectable card,
 *  the recommended (rank-1) one leading and preselected by the caller. Controlled — the
 *  parent owns the selection so the same value drives the repo guidance and the
 *  serve/download call. Engines the host can't run stay visible (disabled) so the
 *  operator sees what isn't available and why.
 *
 *  Frameless on purpose — the caller supplies the surrounding label/border (a flush
 *  `Panel` on the LOCAL MODELS tab, a bordered block in the guided run-locally flow). The
 *  switch-cost reminder lives with the download step (`EngineSwitchNote`), not here. */
export function EnginePicker(props: {
  recs: EngineRecommendation[];
  selected: EngineKind | null;
  onSelect: (engine: EngineKind) => void;
}): JSX.Element {
  const ranked = createMemo(() =>
    [...props.recs].sort((a, b) => a.rank - b.rank),
  );
  return (
    <div role="radiogroup" aria-label="Inference engine">
      <For each={ranked()}>
        {(rec) => (
          <EngineRow
            rec={rec}
            selected={props.selected === rec.engine}
            onSelect={props.onSelect}
          />
        )}
      </For>
    </div>
  );
}
