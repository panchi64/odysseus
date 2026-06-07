import { createResource, createSignal, type Resource } from "solid-js";
import type { Contact } from "./model";
import { mockContacts } from "./mocks";

// Mutable local store so Phase-1 actions visibly work.
let _contacts: Contact[] = mockContacts.map((c) => ({ ...c }));
const [_version, _bumpVersion] = createSignal(0);

// Bump to force a re-read of the local store (used by mutations and retry).
export function refetchContacts(): void {
  _bumpVersion((v) => v + 1);
}

async function fetchContacts(): Promise<Contact[]> {
  // Read the version signal so mutations automatically invalidate the resource.
  _version();
  return _contacts;
}

export function useContacts(): Resource<Contact[]> {
  const [data] = createResource(_version, fetchContacts);
  return data;
}

/** Remove a contact by id. Returns the removed contact (for undo). */
export function deleteContact(id: string): Contact | undefined {
  const idx = _contacts.findIndex((c) => c.id === id);
  if (idx === -1) return undefined;
  const [removed] = _contacts.splice(idx, 1);
  _bumpVersion((v) => v + 1);
  return removed;
}

/** Restore a previously-deleted contact (undo support). */
export function restoreContact(contact: Contact): void {
  _contacts = [contact, ..._contacts];
  _bumpVersion((v) => v + 1);
}

/** Save (upsert) a contact. Creates a new one if id is absent. */
export function saveContact(
  patch: Partial<Contact> & { id?: string },
): Contact {
  if (patch.id) {
    _contacts = _contacts.map((c) =>
      c.id === patch.id ? { ...c, ...patch } : c,
    );
  } else {
    const newContact: Contact = {
      id: `ct-${Date.now()}`,
      name: patch.name ?? "",
      org: patch.org,
      emails: patch.emails ?? [],
      phones: patch.phones ?? [],
      notes: patch.notes,
      synced: false,
      group: (patch.name ?? "?")[0]?.toUpperCase() ?? "?",
    };
    _contacts = [newContact, ..._contacts];
  }
  _bumpVersion((v) => v + 1);
  return _contacts.find((c) => c.id === (patch.id ?? "")) ?? _contacts[0];
}

/** Simulate a CardDAV sync — marks all unsynced contacts as synced. */
export async function syncContacts(): Promise<void> {
  await new Promise<void>((resolve) => setTimeout(resolve, 1200));
  _contacts = _contacts.map((c) => ({ ...c, synced: true }));
  _bumpVersion((v) => v + 1);
}
