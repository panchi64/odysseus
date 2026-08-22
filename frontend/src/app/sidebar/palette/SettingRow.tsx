import { Show, type JSX } from "solid-js";
import { Input, ListRow, Text, type TextTone } from "~/ui";
import { formatSettingValue, type SettingEntry } from "~/app/nav";

export interface SettingRowProps {
  entry: SettingEntry;
  /** DOM id, so the palette's field can point here with `aria-activedescendant`. */
  id: string;
  selected: boolean;
  /** A write is in flight — the readout dims until the seam reports back. */
  busy: boolean;
  /** The inline number field is open on this row. */
  editing: boolean;
  draft: string;
  onDraft: (value: string) => void;
  fieldRef: (el: HTMLInputElement) => void;
  onActivate: () => void;
}

/**
 * One settings row in the palette: its label, its **live** value on the right,
 * and an activation that changes it where it stands rather than navigating.
 *
 * The row itself is the control — `option` semantics with `aria-checked` on a
 * two-state setting — so the right slot stays a readout and never nests a second
 * interactive element announcing the same state twice. The one exception is the
 * inline number field, which replaces the readout while it's open.
 */
export function SettingRow(props: SettingRowProps): JSX.Element {
  const value = (): boolean | number | string | undefined => props.entry.read();
  /** Only a toggle has a checked state to announce; the other kinds must not
   *  claim one, or a screen reader reads a three-option choice as a switch. */
  const checked = (): boolean | undefined =>
    props.entry.kind === "toggle"
      ? (value() as boolean | undefined)
      : undefined;
  // Semantic, not decorative: green is "this is on", and nothing else here is
  // accented. A value still being written back reads dim so the row doesn't
  // assert a state the seam hasn't confirmed.
  const tone = (): TextTone => {
    if (props.busy || value() === undefined) return "dim";
    if (props.entry.kind === "toggle") return value() ? "nominal" : "dim";
    return "bright";
  };

  return (
    <ListRow
      option
      id={props.id}
      selected={props.selected}
      checked={checked()}
      label={props.entry.label}
      leading="settings"
      onClick={props.onActivate}
      right={
        <Show
          when={props.editing && props.entry.kind === "number"}
          fallback={
            <Text variant="micro" tone={tone()}>
              {formatSettingValue(props.entry, value())}
            </Text>
          }
        >
          {/* `text` + `inputMode`, never `type="number"`: the native stepper
              binds ArrowUp/ArrowDown, and those keys belong to the palette's row
              navigation for as long as the overlay is open. */}
          <div class="w-24">
            <Input
              ref={props.fieldRef}
              type="text"
              inputMode="numeric"
              value={props.draft}
              onInput={(e) => props.onDraft(e.currentTarget.value)}
              aria-label={`${props.entry.label} value`}
            />
          </div>
        </Show>
      }
    />
  );
}
