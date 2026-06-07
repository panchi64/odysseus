/** Uploads / PDF feature data contracts. */

export type UploadStatus = "queued" | "extracting" | "done" | "error";

export interface FormField {
  name: string;
  value: string;
}

export interface Upload {
  id: string;
  name: string;
  mime: string;
  sizeBytes: number;
  status: UploadStatus;
  /** Progress 0-100 when status === "extracting". */
  extractionProgress?: number;
  /** Extracted text content (OCR or PDF parse). */
  extractedText?: string;
  /** Detected fillable form fields. */
  formFields?: FormField[];
  /** True when scanned / vision-extracted (not native PDF text). */
  vision?: boolean;
}
