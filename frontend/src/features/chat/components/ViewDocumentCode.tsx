import {
  createMemo,
  createSignal,
  Match,
  Show,
  Switch,
  type JSX,
} from "solid-js";
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
 * FROM/TO version selectors across the document's own committed versions (both bodies are
 * already in hand for every candidate, so any pair diffs freely — no fetch). TO defaults to
 * the entry on stage, FROM to the version immediately before it. The frontend only
 * displays; it decides nothing.
 */
export function ViewDocumentCode(props: {
  document: ViewDocumentRef;
  /** Prior committed versions of the same document (oldest → newest). */
  priorVersions: ViewDocumentRef[];
  /** Forwarded to `CodeBlock`/`DiffView` — the panel's zoom/wrap controls. */
  fontStep?: number;
  softWrap?: boolean;
}): JSX.Element {
  return (
    <Show keyed when={`${props.document.documentId}:${props.document.version}`}>
      {(_key) => (
        <DocumentCodeStage
          document={props.document}
          priorVersions={props.priorVersions}
          fontStep={props.fontStep}
          softWrap={props.softWrap}
        />
      )}
    </Show>
  );
}

/** The actual compare UI — remounted (via the keyed `Show` above) whenever the entry
 *  on stage switches to a different document or version, so its TO/FROM picks always
 *  start clean rather than carrying a stale selection into a document whose version
 *  list doesn't include it. */
function DocumentCodeStage(props: {
  document: ViewDocumentRef;
  priorVersions: ViewDocumentRef[];
  fontStep?: number;
  softWrap?: boolean;
}): JSX.Element {
  // Every version this entry can stand in for as TO: its priors, then itself
  // (the default, and the newest option).
  const allVersions = createMemo<ViewDocumentRef[]>(() => [
    ...props.priorVersions,
    props.document,
  ]);

  // TO — defaults to the entry on stage; freely selectable among any candidate.
  const [toPick, setToPick] = createSignal(String(props.document.version));
  const toDoc = createMemo(
    () =>
      allVersions().find((d) => String(d.version) === toPick()) ??
      props.document,
  );

  // FROM candidates are every version strictly older than the selected TO.
  const fromCandidates = createMemo<ViewDocumentRef[]>(() => {
    const all = allVersions();
    const i = all.findIndex((d) => d.version === toDoc().version);
    return i <= 0 ? [] : all.slice(0, i);
  });
  const defaultFromId = createMemo(
    () => fromCandidates().at(-1)?.version.toString() ?? NO_DIFF,
  );
  // Explicit FROM pick; null = follow the default. Reset whenever TO changes so
  // a stale pick can't outlive it.
  const [fromPick, setFromPick] = createSignal<string | null>(null);
  const fromId = createMemo(() => fromPick() ?? defaultFromId());

  const setTo = (v: string): void => {
    setToPick(v);
    setFromPick(null);
  };

  const fromBody = createMemo<string | null>(() => {
    if (fromId() === NO_DIFF) return null;
    const v = Number(fromId());
    return allVersions().find((d) => d.version === v)?.body ?? "";
  });

  // Compare options: TO — every candidate, newest ("this version") last. FROM —
  // full code, then each version older than TO, newest first.
  const toOptions = createMemo<SelectOption[]>(() =>
    allVersions().map((d) => ({
      value: String(d.version),
      label:
        d.version === props.document.version ? "This version" : `V${d.version}`,
    })),
  );
  const fromOptions = createMemo<SelectOption[]>(() => [
    { value: NO_DIFF, label: "No diff · full code" },
    ...[...fromCandidates()].reverse().map((d) => ({
      value: String(d.version),
      label: `Diff vs V${d.version}`,
    })),
  ]);

  return (
    <div class="flex h-full min-h-0 flex-col">
      <div class="flex items-center gap-2 border-b border-line px-3 py-2">
        <Text variant="micro" tone="dim" class="shrink-0">
          TO
        </Text>
        <Select
          aria-label="Compare TO version"
          class="min-w-0 flex-1"
          options={toOptions()}
          value={toPick()}
          onChange={setTo}
        />
        <Text variant="micro" tone="dim" class="shrink-0">
          FROM
        </Text>
        <Select
          aria-label="Compare FROM version"
          class="min-w-0 flex-1"
          options={fromOptions()}
          value={fromId()}
          onChange={(v) => setFromPick(v)}
        />
      </div>
      <div class="min-h-0 flex-1">
        <Switch>
          <Match when={fromId() === NO_DIFF}>
            <CodeBlock
              code={toDoc().body}
              lang="markdown"
              fontStep={props.fontStep}
              softWrap={props.softWrap}
            />
          </Match>
          <Match when={fromId() !== NO_DIFF}>
            <DiffView
              diff={unifiedDiff(fromBody() ?? "", toDoc().body)}
              fontStep={props.fontStep}
              softWrap={props.softWrap}
            />
          </Match>
        </Switch>
      </div>
    </div>
  );
}
