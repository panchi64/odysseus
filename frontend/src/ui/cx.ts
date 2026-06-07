export type ClassValue = string | false | null | undefined;

/** Minimal className joiner. Falsy parts are dropped; later parts win by order. */
export function cx(...parts: ClassValue[]): string {
  return parts.filter(Boolean).join(" ");
}
