import { Show, createSignal, type JSX } from "solid-js";
import { Button } from "./Button";
import { Input } from "./Input";
import { Row } from "../primitives/Row";

export interface PathInputProps {
  label?: string;
  placeholder?: string;
  hint?: string;
  invalid?: boolean;
  disabled?: boolean;
  value: string;
  onChange: (next: string) => void;
  /** Opens a chooser and resolves to the chosen path, or null when cancelled.
   *  Omit it and the BROWSE control isn't rendered at all — the typed field is
   *  always the complete control, never a fallback that half-works. */
  onBrowse?: () => Promise<string | null>;
  browseLabel?: string;
}

/**
 * A filesystem path field, with an optional BROWSE control beside it.
 *
 * Typing is the primary interaction and always works; BROWSE is an enhancement that
 * only appears when the caller can actually open a chooser. The component takes a
 * callback rather than knowing how one is opened — opening a native dialog is the
 * backend's job, and nothing in the design system talks to the API.
 */
export function PathInput(props: PathInputProps): JSX.Element {
  const [browsing, setBrowsing] = createSignal(false);

  async function browse(): Promise<void> {
    if (browsing() || !props.onBrowse) return;
    setBrowsing(true);
    try {
      const picked = await props.onBrowse();
      // A cancelled dialog leaves whatever was typed — it isn't a clear command.
      if (picked) props.onChange(picked);
    } finally {
      setBrowsing(false);
    }
  }

  return (
    <Row gap={2} align="end" class="flex-wrap">
      <div class="min-w-0 flex-1">
        <Input
          label={props.label}
          placeholder={props.placeholder}
          hint={props.hint}
          invalid={props.invalid}
          disabled={props.disabled}
          value={props.value}
          onInput={(e) => props.onChange(e.currentTarget.value)}
        />
      </div>
      <Show when={props.onBrowse}>
        <Button
          variant="ghost"
          leading="library"
          disabled={props.disabled || browsing()}
          onClick={() => void browse()}
        >
          {browsing() ? "CHOOSING…" : (props.browseLabel ?? "BROWSE")}
        </Button>
      </Show>
    </Row>
  );
}
