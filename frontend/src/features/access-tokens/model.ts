/** Access Tokens feature — **inbound** scoped API tokens (`AUTH-4`).
 *
 *  An access token is a credential the operator issues to a *client* so it can call this
 *  API programmatically. The opposite direction from `features/tokens`, which holds the
 *  outbound service keys this system calls third parties with — the two are separate
 *  surfaces and neither reads the other.
 *
 *  The backend shows the plaintext token exactly once, in the issue response, and stores
 *  only a one-way hash of it: a lost token is reissued, never recovered. */

/** One grantable capability group, as the backend declares it. */
export interface TokenScope {
  /** Stable id sent when issuing ("chat", "knowledge"). */
  id: string;
  label: string;
  /** What the scope lets a token reach. */
  description: string;
}

export interface AccessToken {
  id: string;
  /** The operator's own name for this token. */
  label: string;
  /** The token's public half — enough to match a row to a client, never enough to use. */
  prefix: string;
  /** Scope ids this token may reach. */
  scopes: string[];
  createdAt: string;
  /** When it last authenticated, or null if never used. */
  lastUsedAt: string | null;
  /** When it was revoked, or null while it is live. */
  revokedAt: string | null;
}

/** A freshly issued token — the one moment the secret exists outside the client. */
export interface IssuedAccessToken extends AccessToken {
  /** The plaintext, shown once and then unrecoverable. */
  token: string;
}
