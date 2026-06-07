import { createSignal, type JSX } from "solid-js";
import { Modal } from "./Modal";
import { Button } from "./Button";
import { Text } from "../primitives/Text";

/** Promise-based confirmation gate for destructive / consequential actions.
 *  Built on Modal + Button so every guard looks and behaves the same. */
export type ConfirmTone = "alert" | "default";

export interface ConfirmOptions {
  title: string;
  /** Body line; defaults to "This action cannot be undone." */
  detail?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** alert => danger confirm button (destructive). default => primary. */
  tone?: ConfirmTone;
}

interface ConfirmState extends ConfirmOptions {
  resolve: (ok: boolean) => void;
}

const [current, setCurrent] = createSignal<ConfirmState | null>(null);

/** Await a user's confirmation before a dangerous action:
 *  `if (await confirm({ title: "Delete report?", tone: "alert" })) remove();`
 *  Cancel, the X, the backdrop, and Escape all resolve `false`.
 *  Render <ConfirmHost/> once at the app root. */
export function confirm(opts: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    setCurrent((prev) => {
      prev?.resolve(false); // supersede any open dialog as cancelled
      return { ...opts, resolve };
    });
  });
}

function settle(ok: boolean): void {
  const c = current();
  if (!c) return;
  setCurrent(null);
  c.resolve(ok);
}

/** The single confirmation dialog outlet. Mount once at the root. */
export function ConfirmHost(): JSX.Element {
  return (
    <Modal
      open={current() !== null}
      onClose={() => settle(false)}
      title={current()?.title}
      footer={
        <>
          <Button variant="ghost" onClick={() => settle(false)}>
            {current()?.cancelLabel ?? "CANCEL"}
          </Button>
          <Button
            variant={current()?.tone === "alert" ? "danger" : "primary"}
            onClick={() => settle(true)}
          >
            {current()?.confirmLabel ?? "CONFIRM"}
          </Button>
        </>
      }
    >
      <Text tone="dim">
        {current()?.detail ?? "This action cannot be undone."}
      </Text>
    </Modal>
  );
}
