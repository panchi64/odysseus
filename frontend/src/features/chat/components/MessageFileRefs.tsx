import { For, Show, type JSX } from "solid-js";
import { AttachmentChip } from "~/ui";

interface MessageFileRefsProps {
  /** Workspace-relative paths the operator named with `@` on this sent turn. */
  paths: string[];
}

/**
 * The `@` references on a sent user turn, as read-only chips.
 *
 * **These are the ones the backend actually resolved**, which is the whole reason they
 * are worth rendering beside a message that already contains the paths as text: a
 * reference that did not resolve — a typo, a file that only exists in the operator's own
 * checkout and not in the thread's worktree — is silently dropped from the turn, and
 * without this row the only evidence would be the model not mentioning it.
 *
 * The chip leads with the basename because that is what the operator was looking for; the
 * full path is on the title, for the moment they need to tell two `index.ts` apart. No
 * link: a reference is a path in the thread's workspace, not a file the browser can open,
 * and the text of the message beside it already carries it in full.
 */
export function MessageFileRefs(props: MessageFileRefsProps): JSX.Element {
  return (
    <Show when={props.paths.length > 0}>
      <div class="flex max-w-[80%] flex-wrap items-end justify-end gap-2">
        <For each={props.paths}>
          {(path) => (
            <span title={path}>
              <AttachmentChip name={path.split("/").pop() || path} />
            </span>
          )}
        </For>
      </div>
    </Show>
  );
}
