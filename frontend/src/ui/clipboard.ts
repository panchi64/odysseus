import { toast } from "./components/Toast";

/**
 * Copy text to the clipboard and surface the result via toast. Centralizes the
 * `navigator.clipboard.writeText` + success/error-toast pattern that otherwise
 * gets re-inlined per screen (settings, users, tokens, vault, code).
 */
export function copyToClipboard(value: string, label = "Value"): void {
  navigator.clipboard.writeText(value).then(
    () => toast.success(`${label} copied`),
    () => toast.error("Copy failed"),
  );
}
