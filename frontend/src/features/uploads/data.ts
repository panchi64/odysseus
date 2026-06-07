import { createSignal } from "solid-js";
import type { Upload } from "./model";
import { mockUploads } from "./mocks";

const [uploads, setUploads] = createSignal<Upload[]>([...mockUploads]);

export function useUploads() {
  return uploads;
}

export function removeUpload(id: string): Upload | undefined {
  const removed = uploads().find((u) => u.id === id);
  setUploads((prev) => prev.filter((u) => u.id !== id));
  return removed;
}

export function restoreUpload(upload: Upload): void {
  setUploads((prev) => [...prev, upload]);
}

export function retryExtraction(id: string): void {
  setUploads((prev) =>
    prev.map((u) =>
      u.id === id ? { ...u, status: "extracting", extractionProgress: 0 } : u,
    ),
  );
  // Simulate extraction completing after 2 seconds (Phase 1 mock)
  setTimeout(() => {
    setUploads((prev) =>
      prev.map((u) =>
        u.id === id
          ? {
              ...u,
              status: "done",
              extractionProgress: 100,
              extractedText: "Re-extracted content — OCR retry succeeded.",
              formFields: [],
            }
          : u,
      ),
    );
  }, 2000);
}

export function addMockUpload(name: string): Upload {
  const id = `u-mock-${Date.now()}`;
  const upload: Upload = {
    id,
    name,
    mime: name.endsWith(".pdf") ? "application/pdf" : "image/jpeg",
    sizeBytes: Math.floor(Math.random() * 500_000) + 50_000,
    status: "queued",
    vision: false,
  };
  setUploads((prev) => [upload, ...prev]);
  return upload;
}
