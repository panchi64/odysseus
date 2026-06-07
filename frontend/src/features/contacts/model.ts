/** Contacts feature data contracts. */

export interface Contact {
  id: string;
  name: string;
  org?: string;
  emails: string[];
  phones: string[];
  notes?: string;
  synced: boolean;
  /** First letter of name for alpha grouping. */
  group: string;
}
