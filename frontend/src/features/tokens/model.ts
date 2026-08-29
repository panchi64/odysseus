/** API Tokens feature — outbound service credentials.
 *
 *  A credential is an API key the system uses to call a third-party service on the
 *  operator's behalf — today, the mail OAuth clients. The set of services is the
 *  backend's catalog; the key itself is write-only, and the API only ever reports
 *  whether one is set. */
export interface ServiceCredential {
  /** Stable service id the key authenticates to (e.g. "google_oauth"). */
  service: string;
  label: string;
  /** What the system uses this key for. */
  purpose: string;
  /** Where the operator mints the key. */
  docsUrl: string;
  /** Whether a key is currently stored (the value is never returned). */
  hasKey: boolean;
}
