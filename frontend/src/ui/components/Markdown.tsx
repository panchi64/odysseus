import { createMemo, splitProps, type JSX } from "solid-js";
import { marked } from "marked";
import { cx } from "../cx";

export interface MarkdownProps {
  /** Markdown source. Rendered with token-styled prose (.ody-prose). */
  children: string;
  class?: string;
}

marked.setOptions({ gfm: true, breaks: true });

/**
 * Renders markdown as structured, token-styled prose. Used for assistant
 * replies, research reports, and document bodies.
 *
 * NOTE (Phase 2): mock content is trusted, so output is injected directly.
 * When real LLM/user-authored markdown is wired in, sanitize the HTML (e.g.
 * DOMPurify) before injection.
 */
export function Markdown(props: MarkdownProps): JSX.Element {
  const [local] = splitProps(props, ["children", "class"]);
  const html = createMemo(
    () => marked.parse(local.children ?? "", { async: false }) as string,
  );
  return <div class={cx("ody-prose", local.class)} innerHTML={html()} />;
}
