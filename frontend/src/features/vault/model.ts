/** Password vault feature data contracts. */

export interface VaultEntry {
  id: string;
  name: string;
  username: string;
  url: string;
  password: string;
}

export interface VaultState {
  /** Whether a vault exists at all. False ⇒ the operator is choosing a passphrase,
   *  not entering one — the backend distinguishes the two and the screen must too. */
  configured: boolean;
  locked: boolean;
}

/** What the operator types when adding a credential. */
export interface VaultEntryInput {
  name: string;
  username: string;
  url: string;
  password: string;
}
