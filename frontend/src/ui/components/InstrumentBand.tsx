import { For, splitProps, type JSX } from "solid-js";
import { cx } from "../cx";
import { Text, type TextTone } from "../primitives/Text";

export interface BandCell {
  label: string;
  value: JSX.Element;
  tone?: TextTone;
}

export interface InstrumentBandProps {
  /** Densely packed label/value cells, separated by hairlines. */
  items: BandCell[];
  class?: string;
}

/** Full-width strip of dense fields divided by hairlines (§6.3). This is where
 *  density is most aggressive — space-2 padding only. */
export function InstrumentBand(props: InstrumentBandProps): JSX.Element {
  const [local] = splitProps(props, ["items", "class"]);
  return (
    <div
      class={cx(
        "flex flex-wrap items-stretch divide-x divide-line border border-line bg-surface",
        local.class,
      )}
    >
      <For each={local.items}>
        {(cell) => (
          <div class="flex min-w-0 flex-col gap-0.5 px-2 py-2">
            <Text variant="label" tone="dim">
              {cell.label}
            </Text>
            <Text variant="body" tone={cell.tone ?? "bright"}>
              {cell.value}
            </Text>
          </div>
        )}
      </For>
    </div>
  );
}
