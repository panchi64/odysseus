/** Uploads / PDF feature data contracts. */

export type UploadStatus = "queued" | "extracting" | "done" | "error";

export interface Upload {
  id: string;
  name: string;
  mime: string;
  sizeBytes: number;
  status: UploadStatus;
  /** Extracted text content (native PDF text or vision OCR). Present on detail. */
  extractedText?: string;
  /** True when scanned / vision-extracted (not native PDF text). */
  vision?: boolean;
  /** Which extractor produced the text: "basic" (built-in), "mineru" (high-fidelity),
   *  or "manual" (operator-corrected). Lets the UI flag built-in extractions. */
  extractor?: string;
  /** A short note when extraction was bounded or degraded (e.g. no vision model,
   *  pages skipped), or the failure reason when status is "error". */
  note?: string;
  /** When true, the file's text is excluded from the knowledge base / retrieval
   *  corpus (still stored and attachable, just not indexed for recall). */
  kbExcluded?: boolean;
}
