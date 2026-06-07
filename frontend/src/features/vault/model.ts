/** Password vault feature data contracts. */

export interface VaultEntry {
  id: string;
  name: string;
  username: string;
  url: string;
  password: string;
}

export interface VaultState {
  locked: boolean;
}
