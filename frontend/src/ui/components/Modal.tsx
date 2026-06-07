import { Show, splitProps, type JSX } from "solid-js";
import { Portal } from "solid-js/web";
import { cx } from "../cx";
import { Text } from "../primitives/Text";
import { Icon } from "../primitives/Icon";

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  /** Footer actions, right-aligned. */
  footer?: JSX.Element;
  /** Max-width utility class override (default narrow column). */
  class?: string;
  children: JSX.Element;
}

/** Centered dialog over a dim backdrop. Appears instantly (no fade). */
export function Modal(props: ModalProps): JSX.Element {
  const [local] = splitProps(props, [
    "open",
    "onClose",
    "title",
    "footer",
    "class",
    "children",
  ]);
  return (
    <Show when={local.open}>
      <Portal>
        <div
          class="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 p-4"
          onClick={local.onClose}
        >
          <div
            role="dialog"
            aria-modal="true"
            class={cx(
              "flex max-h-[85vh] w-full max-w-md flex-col border border-line bg-surface",
              local.class,
            )}
            onClick={(e) => e.stopPropagation()}
          >
            <Show when={local.title}>
              <header class="flex items-center justify-between border-b border-line px-4 py-2">
                <Text variant="label" tone="bright">
                  {local.title}
                </Text>
                <button
                  type="button"
                  onClick={local.onClose}
                  aria-label="Close"
                  class="text-dim transition-colors hover:text-bright"
                >
                  <Icon name="close" size={14} />
                </button>
              </header>
            </Show>
            <div class="min-h-0 flex-1 overflow-auto p-4">{local.children}</div>
            <Show when={local.footer}>
              <footer class="flex items-center justify-end gap-2 border-t border-line px-4 py-2">
                {local.footer}
              </footer>
            </Show>
          </div>
        </div>
      </Portal>
    </Show>
  );
}
