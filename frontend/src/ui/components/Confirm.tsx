import { createSignal, Show, type JSX } from "solid-js";
import { Modal } from "./Modal";
import { Button } from "./Button";
import { Input } from "./Input";
import { Stack } from "../primitives/Stack";
import { Text } from "../primitives/Text";

/** Promise-based confirmation gate for destructive / consequential actions.
 *  Built on Modal + Button so every guard looks and behaves the same. */
export type ConfirmTone = "alert" | "default";

/** The outcome of a three-way prompt: the primary (destructive) action, the
 *  secondary (alternative) action, or dismissal. `confirm` collapses this to a
 *  boolean (primary ⇒ true, everything else ⇒ false). */
export type ConfirmChoice = "primary" | "secondary" | "cancel";

export interface ConfirmOptions {
  title: string;
  /** Body line; defaults to "This action cannot be undone." */
  detail?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** alert => danger confirm button (destructive). default => primary. */
  tone?: ConfirmTone;
  /** When set, the confirm button stays disabled until the operator types this
   *  word exactly. For the small class of actions where a mis-click is
   *  unrecoverable — not a general "are you sure" upgrade, which would only
   *  train the reflex it exists to interrupt. */
  requireText?: string;
}

export interface ConfirmChoiceOptions extends ConfirmOptions {
  /** When set, a third (middle) button offering an alternative to the primary
   *  action — e.g. "Keep images" beside a "Delete images" primary. */
  secondaryLabel: string;
}

interface ConfirmState extends ConfirmOptions {
  secondaryLabel?: string;
  resolve: (choice: ConfirmChoice) => void;
}

const [current, setCurrent] = createSignal<ConfirmState | null>(null);

/** Await a user's confirmation before a dangerous action:
 *  `if (await confirm({ title: "Delete report?", tone: "alert" })) remove();`
 *  Cancel, the X, the backdrop, and Escape all resolve `false`.
 *  Render <ConfirmHost/> once at the app root. */
export function confirm(opts: ConfirmOptions): Promise<boolean> {
  return choose(opts).then((choice) => choice === "primary");
}

/** Three-way variant: a destructive primary, an alternative secondary, and
 *  cancel. `await confirmChoice({ ..., confirmLabel: "Delete images",
 *  secondaryLabel: "Keep images" })` ⇒ "primary" | "secondary" | "cancel".
 *  Cancel / X / backdrop / Escape resolve "cancel". Same outlet as confirm. */
export function confirmChoice(
  opts: ConfirmChoiceOptions,
): Promise<ConfirmChoice> {
  return choose(opts);
}

function choose(
  opts: ConfirmOptions | ConfirmChoiceOptions,
): Promise<ConfirmChoice> {
  return new Promise((resolve) => {
    setCurrent((prev) => {
      prev?.resolve("cancel"); // supersede any open dialog as cancelled
      return { ...opts, resolve };
    });
  });
}

function settle(choice: ConfirmChoice): void {
  const c = current();
  if (!c) return;
  setCurrent(null);
  setTyped("");
  c.resolve(choice);
}

/** The gate word as typed so far. Held beside `current` rather than inside it so
 *  opening a dialog can't inherit the previous one's progress. */
const [typed, setTyped] = createSignal("");

const gated = (): boolean => {
  const want = current()?.requireText;
  return want !== undefined && typed() !== want;
};

/** The single confirmation dialog outlet. Mount once at the root. */
export function ConfirmHost(): JSX.Element {
  return (
    <Modal
      open={current() !== null}
      onClose={() => settle("cancel")}
      title={current()?.title}
      footer={
        <>
          <Button variant="ghost" onClick={() => settle("cancel")}>
            {current()?.cancelLabel ?? "Cancel"}
          </Button>
          <Show when={current()?.secondaryLabel}>
            {(label) => (
              <Button variant="default" onClick={() => settle("secondary")}>
                {label()}
              </Button>
            )}
          </Show>
          <Button
            variant={current()?.tone === "alert" ? "danger" : "primary"}
            disabled={gated()}
            onClick={() => settle("primary")}
          >
            {current()?.confirmLabel ?? "Confirm"}
          </Button>
        </>
      }
    >
      <Stack gap={3}>
        <Text tone="dim">
          {current()?.detail ?? "This action cannot be undone."}
        </Text>
        <Show when={current()?.requireText}>
          {(word) => (
            <Input
              label={`Type ${word()} to confirm`}
              value={typed()}
              onInput={(e) => setTyped(e.currentTarget.value)}
              autocomplete="off"
              spellcheck={false}
            />
          )}
        </Show>
      </Stack>
    </Modal>
  );
}
