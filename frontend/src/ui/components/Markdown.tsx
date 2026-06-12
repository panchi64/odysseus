import {
  createEffect,
  createMemo,
  onCleanup,
  splitProps,
  type JSX,
} from "solid-js";
import { marked } from "marked";
import { cx } from "../cx";
import { copyToClipboard } from "../clipboard";

export interface MarkdownProps {
  /** Markdown source. Rendered with token-styled prose (.ody-prose). */
  children: string;
  class?: string;
  /** Add a hover copy button to each rendered code block. Default true. */
  copyCode?: boolean;
}

marked.setOptions({ gfm: true, breaks: true });

/** Token-classed copy affordance injected into the top-right of each `pre`. Built
 *  as a detached node (not innerHTML) so the markup stays theme-safe and the click
 *  is handled by delegation rather than inline scripting. */
function makeCopyButton(): HTMLButtonElement {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.dataset.codeCopy = "";
  btn.setAttribute("aria-label", "Copy code");
  btn.className =
    "ody-code-copy absolute right-1 top-1 hidden border border-line bg-raised px-2 py-0.5 text-micro uppercase tracking-label text-dim transition-colors hover:text-bright group-hover/code:block focus:block focus:outline-none";
  btn.textContent = "COPY";
  return btn;
}

/**
 * Renders markdown as structured, token-styled prose. Used for assistant
 * replies, research reports, and document bodies. Each fenced code block gets a
 * hover copy button (top-right) that copies the block's clean source — no fences.
 *
 * NOTE (Phase 2): mock content is trusted, so output is injected directly.
 * When real LLM/user-authored markdown is wired in, sanitize the HTML (e.g.
 * DOMPurify) before injection.
 */
export function Markdown(props: MarkdownProps): JSX.Element {
  const [local] = splitProps(props, ["children", "class", "copyCode"]);
  const html = createMemo(
    () => marked.parse(local.children ?? "", { async: false }) as string,
  );

  let ref: HTMLDivElement | undefined;

  // Post-render enhancement: wrap each <pre> in a relative `group/code` host and
  // drop in a copy button. Re-runs whenever the rendered HTML changes (streaming
  // answers re-parse on every delta), and is idempotent per <pre>.
  const enhance = (): void => {
    if (!ref || local.copyCode === false) return;
    const pres = ref.querySelectorAll<HTMLPreElement>("pre");
    pres.forEach((pre) => {
      if (pre.parentElement?.dataset.codeHost !== undefined) return;
      const host = document.createElement("div");
      host.dataset.codeHost = "";
      host.className = "group/code relative";
      pre.replaceWith(host);
      host.appendChild(pre);
      host.appendChild(makeCopyButton());
    });
  };

  createEffect(() => {
    const enabled = local.copyCode !== false; // re-runs when toggled (stream end)
    html(); // track re-parses (streaming deltas) so new blocks get enhanced
    // Skip scheduling entirely while disabled (e.g. a streaming answer), so a long
    // stream doesn't re-scan/re-wrap the DOM on every token.
    if (enabled) queueMicrotask(enhance);
  });

  // One delegated click handler copies the sibling <code>'s text (already clean).
  const onClick = (e: MouseEvent): void => {
    const target = e.target as HTMLElement;
    const btn = target.closest<HTMLButtonElement>("[data-code-copy]");
    if (!btn) return;
    const code = btn.parentElement?.querySelector("pre code, pre");
    copyToClipboard(code?.textContent ?? "", "Code");
  };

  onCleanup(() => ref?.removeEventListener("click", onClick));

  return (
    <div
      ref={(el) => {
        ref = el;
        el.addEventListener("click", onClick);
        queueMicrotask(enhance);
      }}
      class={cx("ody-prose", local.class)}
      innerHTML={html()}
    />
  );
}
