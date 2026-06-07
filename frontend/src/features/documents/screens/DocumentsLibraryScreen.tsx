import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  EmptyState,
  InstrumentBand,
  ListRow,
  LoadingText,
  Menu,
  PageHeader,
  Panel,
  Stack,
  StatusFlag,
  Tabs,
  Text,
  type Status,
} from "~/ui";
import { relativeTime } from "~/lib/format";
import { useDocuments } from "../data";
import type { DocStatus } from "../model";

const statusMap: Record<DocStatus, Status> = {
  active: "nominal",
  archived: "idle",
};

function WordCount(props: { words: number }): JSX.Element {
  return (
    <Text variant="micro" tone="dim">
      {props.words.toLocaleString()} W
    </Text>
  );
}

export function DocumentsLibraryScreen(): JSX.Element {
  const documents = useDocuments();
  const [tab, setTab] = createSignal<DocStatus>("active");
  const [query, setQuery] = createSignal("");

  const filtered = () => {
    const all = documents() ?? [];
    const q = query().toLowerCase();
    return all
      .filter((d) => d.status === tab())
      .filter(
        (d) =>
          !q ||
          d.title.toLowerCase().includes(q) ||
          d.snippet.toLowerCase().includes(q),
      );
  };

  const totalActive = () =>
    (documents() ?? []).filter((d) => d.status === "active").length;
  const totalArchived = () =>
    (documents() ?? []).filter((d) => d.status === "archived").length;

  return (
    <Stack gap={6}>
      <PageHeader
        title="DOCUMENTS"
        subtitle="Personal knowledge base and working notes."
        assetId="ODY-DOC-01.0"
        actions={
          <Button variant="primary" leading="plus">
            NEW DOCUMENT
          </Button>
        }
      />

      <InstrumentBand
        items={[
          { label: "TOTAL", value: String((documents() ?? []).length) },
          { label: "ACTIVE", value: String(totalActive()), tone: "nominal" },
          { label: "ARCHIVED", value: String(totalArchived()), tone: "dim" },
        ]}
      />

      <Panel flush>
        <div class="flex items-center gap-3 border-b border-line px-4 py-2">
          <Tabs
            items={[
              { value: "active", label: "ACTIVE" },
              { value: "archived", label: "ARCHIVED" },
            ]}
            value={tab()}
            onChange={(v) => setTab(v as DocStatus)}
            class="flex-1"
          />
          <input
            type="search"
            placeholder="SEARCH..."
            value={query()}
            onInput={(e) => setQuery(e.currentTarget.value)}
            class="w-48 border border-line bg-bg px-3 py-1.5 font-mono text-label uppercase tracking-label text-text placeholder:text-dim focus:border-bright focus:outline-none"
          />
        </div>

        <Suspense
          fallback={
            <div class="p-4">
              <LoadingText />
            </div>
          }
        >
          <Show
            when={filtered().length}
            fallback={
              <EmptyState
                icon="file"
                message={
                  tab() === "active"
                    ? "NO ACTIVE DOCUMENTS"
                    : "NO ARCHIVED DOCUMENTS"
                }
                hint={
                  tab() === "active"
                    ? "Create a document to get started."
                    : "Archived documents appear here."
                }
              />
            }
          >
            <For each={filtered()}>
              {(doc) => (
                <ListRow
                  label={doc.title}
                  leading="file"
                  href={`/documents/${doc.id}`}
                  right={
                    <span class="flex items-center gap-3">
                      <WordCount words={doc.words} />
                      <Text variant="micro" tone="dim">
                        {relativeTime(doc.updatedAt)}
                      </Text>
                      <StatusFlag status={statusMap[doc.status]}>
                        {doc.status.toUpperCase()}
                      </StatusFlag>
                      <Menu
                        trigger={
                          <span class="px-1 text-dim hover:text-bright">
                            <Text variant="micro">···</Text>
                          </span>
                        }
                        items={[
                          { label: "OPEN", icon: "file", onSelect: () => {} },
                          {
                            label:
                              doc.status === "active" ? "ARCHIVE" : "RESTORE",
                            icon: "archive",
                            onSelect: () => {},
                          },
                          {
                            label: "DELETE",
                            icon: "trash",
                            danger: true,
                            onSelect: () => {},
                          },
                        ]}
                      />
                    </span>
                  }
                />
              )}
            </For>
          </Show>
        </Suspense>
      </Panel>
    </Stack>
  );
}
