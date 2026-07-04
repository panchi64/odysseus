import { createMemo, createSignal, Match, Switch, type JSX } from "solid-js";
import { CodeBlock, DiffView, Select, Text, type SelectOption } from "~/ui";
import { lineDiff } from "~/features/documents/diff";
import type { ViewDocumentRef } from "../model";

/** "Compare vs" value for plain code (no diff). */
const NO_DIFF = "";

/** Format two bodies (already in hand) as unified-diff text for `DiffView`, reusing the
 *  shared line-level `lineDiff` (LCS) rather than a second copy of the algorithm. */
function unifiedDiff(before: string, after: string): string {
  return lineDiff(before, after)
    .lines.map(
      (l) =>
        `${l.kind === "add" ? "+" : l.kind === "del" ? "-" : " "}${l.text}`,
    )
    .join("\n");
}

/**
 * Renders a document version's **CODE** — its raw markdown source in a `CodeBlock`, plus
 * a "Compare vs" selector across the prior committed versions of the SAME document. When
 * a prior version is picked, a client-side `DiffView` of that version's body → this
 * version's body is shown (all bodies are already in hand, so no fetch). The frontend
 * only displays; it decides nothing.
 */
export function ViewDocumentCode(props: {
  document: ViewDocumentRef;
  /** Prior committed versions of the same document (oldest → newest). */
  priorVersions: ViewDocumentRef[];
}): JSX.Element {
  // The previous version (default compare target), or "" when there is none.
  const previousId = createMemo(() => {
    const priors = props.priorVersions;
    return priors.length ? String(priors[priors.length - 1].version) : NO_DIFF;
  });
  // Explicit compare pick; null = follow the default (previous version).
  const [base, setBase] = createSignal<string | null>(null);
  const baseId = createMemo(() => base() ?? previousId());

  const priorBody = createMemo(() => {
    const v = Number(baseId());
    return props.priorVersions.find((d) => d.version === v)?.body ?? "";
  });

  // Compare options: full code, then each prior version (newest first).
  const compareOptions = createMemo<SelectOption[]>(() => [
    { value: NO_DIFF, label: "No diff · full code" },
    ...[...props.priorVersions].reverse().map((d) => ({
      value: String(d.version),
      label: `Diff vs V${d.version}`,
    })),
  ]);

  return (
    <div class="flex h-full min-h-0 flex-col">
      <div class="flex items-center gap-2 border-b border-line px-3 py-2">
        <Text variant="micro" tone="dim" class="shrink-0">
          COMPARE
        </Text>
        <Select
          aria-label="Compare against version"
          class="min-w-0 flex-1"
          options={compareOptions()}
          value={baseId()}
          onChange={(v) => setBase(v)}
        />
      </div>
      <div class="min-h-0 flex-1">
        <Switch>
          <Match when={baseId() === NO_DIFF}>
            <CodeBlock code={props.document.body} />
          </Match>
          <Match when={baseId() !== NO_DIFF}>
            <DiffView diff={unifiedDiff(priorBody(), props.document.body)} />
          </Match>
        </Switch>
      </div>
    </div>
  );
}
