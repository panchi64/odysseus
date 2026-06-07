import {
  createResource,
  createSignal,
  onCleanup,
  type Resource,
} from "solid-js";
import type { DocumentDetail, DocumentSummary } from "./model";
import { mockDocumentDetail, mockDocuments, mockAiSuggestion } from "./mocks";

async function fetchDocuments(): Promise<DocumentSummary[]> {
  return mockDocuments;
}

async function fetchDocumentDetail(_id: string): Promise<DocumentDetail> {
  return mockDocumentDetail;
}

export function useDocuments(): Resource<DocumentSummary[]> {
  const [data] = createResource(fetchDocuments);
  return data;
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
