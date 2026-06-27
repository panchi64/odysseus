import { For, type JSX } from "solid-js";
import { cx } from "../cx";

export interface CodeBlockProps {
  /** The source text to display, verbatim. */
  code: string;
  class?: string;
}

/** A monospace code view with a dim, tabular line-number gutter. No syntax
 *  highlighting — just a faithful, scrollable rendering that fills its container. */
export function CodeBlock(props: CodeBlockProps): JSX.Element {
  // Split once per render; a trailing newline shouldn't add a phantom blank line.
  const lines = (): string[] => {
    const text = props.code.replace(/\n$/, "");
    return text.length === 0 ? [""] : text.split("\n");
  };
  return (
    <div
      class={cx(
        "h-full overflow-auto bg-surface font-mono text-body",
        props.class,
      )}
    >
      <table class="w-full border-collapse">
        <tbody>
          <For each={lines()}>
            {(line, i) => (
              <tr>
                <td class="select-none whitespace-nowrap px-3 py-0 text-right align-top text-dim tabular-nums">
                  {i() + 1}
                </td>
                <td class="w-full whitespace-pre py-0 pr-3 align-top text-text">
                  {line || " "}
                </td>
              </tr>
            )}
          </For>
        </tbody>
      </table>
    </div>
  );
}
