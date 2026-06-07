import {
  createResource,
  createSignal,
  onCleanup,
  type Resource,
} from "solid-js";
import { createStore, produce } from "solid-js/store";
import type { DocumentDetail, DocumentSummary } from "./model";
import { mockDocumentDetail, mockDocuments, mockAiSuggestion } from "./mocks";

// ---------------------------------------------------------------------------
// Mutable local store — mutated by library actions so Phase-1 changes show up
// ---------------------------------------------------------------------------

const [docStore, setDocStore] = createStore<{ items: DocumentSummary[] }>({
  items: mockDocuments.map((d) => ({ ...d })),
});

/** Delete a document by id from local state. */
export function deleteDocument(id: string): void {
  setDocStore("items", (items) => items.filter((d) => d.id !== id));
}

/** Restore a deleted document back into local state (for undo). */
export function restoreDocument(doc: DocumentSummary): void {
  setDocStore(
    produce((s) => {
      // Only restore if not already present
      if (!s.items.find((d) => d.id === doc.id)) {
        s.items.push(doc);
      }
    }),
  );
}

/** Toggle archive/active status for a document. */
export function toggleArchiveDocument(
  id: string,
  status: "active" | "archived",
): void {
  setDocStore("items", (d) => d.id === id, "status", status);
}

async function fetchDocuments(): Promise<DocumentSummary[]> {
  return docStore.items;
}

async function fetchDocumentDetail(_id: string): Promise<DocumentDetail> {
  return mockDocumentDetail;
}

export function useDocuments(): Resource<DocumentSummary[]> {
  const [data] = createResource(fetchDocuments);
  return data;
}

/** Reactive accessor for the live document list (bypasses resource for
 *  immediate reactivity on local mutations). */
export function useDocumentList(): () => DocumentSummary[] {
  return () => docStore.items;
}

export function useDocumentDetail(id: () => string): Resource<DocumentDetail> {
  const [data] = createResource(id, fetchDocumentDetail);
  return data;
}

/** Mock AI streaming controller for the document editor assist panel. */
let aiCounter = 0;
const nextId = () => `ai-${++aiCounter}`;

export function createAiAssistStream() {
  const [suggestion, setSuggestion] = createSignal("");
  const [streaming, setStreaming] = createSignal(false);
  const timers: ReturnType<typeof setTimeout>[] = [];
  const after = (ms: number, fn: () => void) => timers.push(setTimeout(fn, ms));

  function runAssist(_action: string) {
    if (streaming()) return;
    setSuggestion("");
    setStreaming(true);
    const words = mockAiSuggestion.split(" ");
    words.forEach((_w, i) =>
      after(100 + i * 30, () => setSuggestion(words.slice(0, i + 1).join(" "))),
    );
    after(100 + words.length * 30 + 80, () => setStreaming(false));
    void nextId(); // suppress unused warning
  }

  onCleanup(() => timers.forEach(clearTimeout));
  return { suggestion, streaming, runAssist };
}
