export interface SystemStat {
  label: string;
  value: string;
}

export const mockSystemBand: SystemStat[] = [
  { label: "MODEL", value: "qwen2.5-32b" },
  { label: "TOK/S", value: "82.4" },
  { label: "VRAM", value: "41.2 GB" },
  { label: "CTX", value: "32768" },
  { label: "SESSIONS", value: "14" },
  { label: "UPLINK", value: "12 MS" },
];

export interface ServiceHealth {
  name: string;
  status: "nominal" | "warn" | "alert";
  detail: string;
}

export const mockServices: ServiceHealth[] = [
  { name: "VECTOR SEARCH", status: "nominal", detail: "chroma · 4214 docs" },
  { name: "WEB SEARCH", status: "nominal", detail: "searxng · 38ms" },
  { name: "EMAIL SYNC", status: "warn", detail: "imap · last 14m ago" },
  { name: "PUSH (NTFY)", status: "nominal", detail: "connected" },
  { name: "MODEL ENDPOINT", status: "nominal", detail: "local · healthy" },
  { name: "EMBEDDINGS", status: "alert", detail: "reindex required" },
];
