import { createMemo, createSignal, For, Show, type JSX } from "solid-js";
import {
  Button,
  confirm,
  Drawer,
  EmptyState,
  Field,
  Input,
  InstrumentBand,
  ListRow,
  LoadingText,
  Modal,
  PageHeader,
  Panel,
  Resource,
  Row,
  Stack,
  StatusFlag,
  Text,
  Textarea,
  toast,
  Tooltip,
} from "~/ui";
import {
  deleteContact,
  refetchContacts,
  restoreContact,
  saveContact,
  syncContacts,
  useContacts,
} from "../data";
import type { Contact } from "../model";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function ContactsScreen(): JSX.Element {
  const contacts = useContacts();
  const [search, setSearch] = createSignal("");
  const [selectedId, setSelectedId] = createSignal<string | null>(null);
  const [detailOpen, setDetailOpen] = createSignal(false);
  const [editOpen, setEditOpen] = createSignal(false);
  const [editTargetId, setEditTargetId] = createSignal<string | null>(null);
  const [syncing, setSyncing] = createSignal(false);

  // Edit form state
  const [editName, setEditName] = createSignal("");
  const [editOrg, setEditOrg] = createSignal("");
  const [editEmail, setEditEmail] = createSignal("");
  const [editPhone, setEditPhone] = createSignal("");
  const [editNotes, setEditNotes] = createSignal("");
  const [editError, setEditError] = createSignal<string | null>(null);

  const filtered = createMemo(() => {
    const q = search().toLowerCase();
    return (contacts() ?? []).filter(
      (c) =>
        !q ||
        c.name.toLowerCase().includes(q) ||
        c.org?.toLowerCase().includes(q) ||
        c.emails.some((e) => e.toLowerCase().includes(q)),
    );
  });

  const selectedContact = (): Contact | undefined =>
    (contacts() ?? []).find((c) => c.id === selectedId());

  // Group by first letter
  const grouped = createMemo(() => {
    const map = new Map<string, Contact[]>();
    for (const c of filtered()) {
      const g = c.group;
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(c);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  });

  const syncedCount = () => (contacts() ?? []).filter((c) => c.synced).length;
  const totalCount = () => (contacts() ?? []).length;

  function openContact(c: Contact) {
    setSelectedId(c.id);
    setDetailOpen(true);
  }

  function openEdit(c?: Contact) {
    setEditTargetId(c?.id ?? null);
    setEditError(null);
    if (c) {
      setEditName(c.name);
      setEditOrg(c.org ?? "");
      setEditEmail(c.emails[0] ?? "");
      setEditPhone(c.phones[0] ?? "");
      setEditNotes(c.notes ?? "");
    } else {
      setEditName("");
      setEditOrg("");
      setEditEmail("");
      setEditPhone("");
      setEditNotes("");
    }
    setEditOpen(true);
  }

  // Fix 1 — SYNC button: show loading state, toast on complete/error
  async function handleSync() {
    setSyncing(true);
    try {
      await syncContacts();
      toast.success("SYNC COMPLETE — all contacts synced from CardDAV");
    } catch {
      toast.error("SYNC FAILED — could not reach CardDAV server");
    } finally {
      setSyncing(false);
    }
  }

  // Fix 2 — Delete: confirm before destroying, toast with UNDO
  async function handleDelete(contact: Contact) {
    const ok = await confirm({
      title: `Delete "${contact.name}"?`,
      detail:
        "This contact will be permanently removed. This cannot be undone.",
      confirmLabel: "DELETE",
      tone: "alert",
    });
    if (!ok) return;

    const removed = deleteContact(contact.id);
    setDetailOpen(false);
    setSelectedId(null);

    if (removed) {
      toast.success(`Deleted ${contact.name}`, {
        action: {
          label: "UNDO",
          onClick: () => {
            restoreContact(removed);
            toast.success(`${contact.name} restored`);
          },
        },
      });
    }
  }

  // Fix 3 — Save: validate email, toast on success
  function handleSave() {
    const name = editName().trim();
    const email = editEmail().trim();

    if (!name) {
      setEditError("FULL NAME IS REQUIRED");
      return;
    }
    if (email && !EMAIL_RE.test(email)) {
      setEditError("INVALID EMAIL FORMAT");
      return;
    }

    const isNew = !editTargetId();
    saveContact({
      id: editTargetId() ?? undefined,
      name,
      org: editOrg().trim() || undefined,
      emails: email ? [email] : [],
      phones: editPhone().trim() ? [editPhone().trim()] : [],
      notes: editNotes().trim() || undefined,
    });

    setEditOpen(false);
    toast.success(isNew ? "CONTACT CREATED" : "CONTACT SAVED");
  }

  // Count local-only contacts for the banner
  const localOnlyCount = () => totalCount() - syncedCount();

  return (
    <Stack gap={6}>
      <PageHeader
        title="CONTACTS"
        subtitle="CardDAV-synced address book."
        assetId="COMM-CTC-01.0"
        actions={
          <Row gap={2}>
            {/* Fix 1 — SYNC with loading feedback */}
            <Show when={!syncing()} fallback={<LoadingText label="SYNCING" />}>
              <Button
                variant="ghost"
                leading="refresh"
                size="sm"
                onClick={() => void handleSync()}
              >
                SYNC
              </Button>
            </Show>
            <Button variant="primary" leading="plus" onClick={() => openEdit()}>
              NEW CONTACT
            </Button>
          </Row>
        }
      />

      {/* Fix 4 — local-only banner with configure link hint */}
      <Show when={localOnlyCount() > 0 && !syncing()}>
        <Row
          gap={2}
          align="center"
          class="border border-warn/40 bg-surface px-3 py-2"
        >
          <StatusFlag status="warn" dot>
            {`${localOnlyCount()} LOCAL-ONLY`}
          </StatusFlag>
          <Text variant="micro" tone="dim" class="flex-1">
            These contacts are not synced to CardDAV.
          </Text>
          <Tooltip
            label="Configure CardDAV in Settings → Integrations to sync all contacts."
            side="left"
          >
            <Button variant="ghost" size="sm">
              WHY?
            </Button>
          </Tooltip>
        </Row>
      </Show>

      {/* Fix 5 — wrap resource in <Resource> for error arm */}
      <Resource
        data={contacts}
        loadingLabel="LOADING CONTACTS"
        errorMessage="FAILED TO LOAD CONTACTS"
        onRetry={refetchContacts}
        isEmpty={(list) => list.length === 0}
        emptyMessage="NO CONTACTS"
        emptyHint="No contacts found."
        empty={
          <EmptyState
            icon="users"
            message="NO CONTACTS"
            hint="No contacts match the current filter."
            action={
              <Button variant="default" onClick={() => openEdit()}>
                ADD CONTACT
              </Button>
            }
          />
        }
      >
        {() => (
          <Stack gap={4}>
            <InstrumentBand
              items={[
                { label: "TOTAL", value: String(totalCount()) },
                {
                  label: "SYNCED (CARDDAV)",
                  value: String(syncedCount()),
                  tone: "nominal",
                },
                {
                  label: "LOCAL ONLY",
                  value: String(localOnlyCount()),
                  tone: localOnlyCount() > 0 ? "warn" : "dim",
                },
                { label: "SHOWING", value: String(filtered().length) },
              ]}
            />

            <Row gap={3} align="center">
              <Input
                value={search()}
                onInput={(e) => setSearch(e.currentTarget.value)}
                placeholder="SEARCH NAME, ORG, EMAIL…"
                class="flex-1"
              />
              <Show when={search()}>
                <Button
                  variant="ghost"
                  leading="close"
                  size="sm"
                  onClick={() => setSearch("")}
                >
                  CLEAR
                </Button>
              </Show>
            </Row>

            <Show
              when={filtered().length}
              fallback={
                <EmptyState
                  icon="users"
                  message="NO CONTACTS"
                  hint="No contacts match the current filter."
                  action={
                    <Button variant="default" onClick={() => openEdit()}>
                      ADD CONTACT
                    </Button>
                  }
                />
              }
            >
              <Stack gap={4}>
                <For each={grouped()}>
                  {([letter, group]) => (
                    <Stack gap={0}>
                      <Row gap={2} align="center" class="mb-1">
                        <Text variant="label" tone="dim">
                          {letter}
                        </Text>
                        <div class="flex-1 border-t border-line" />
                      </Row>
                      <Panel flush>
                        <For each={group}>
                          {(contact) => (
                            <ListRow
                              label={contact.name}
                              leading="user"
                              selected={contact.id === selectedId()}
                              onClick={() => openContact(contact)}
                              right={
                                <Row gap={2} align="center">
                                  <Show when={contact.org}>
                                    <Text variant="micro" tone="dim">
                                      {contact.org}
                                    </Text>
                                  </Show>
                                  <StatusFlag
                                    status={contact.synced ? "nominal" : "idle"}
                                  >
                                    {contact.synced ? "SYNCED" : "LOCAL"}
                                  </StatusFlag>
                                </Row>
                              }
                            />
                          )}
                        </For>
                      </Panel>
                    </Stack>
                  )}
                </For>
              </Stack>
            </Show>
          </Stack>
        )}
      </Resource>

      {/* Contact detail drawer */}
      <Show when={selectedContact()}>
        {(contact) => (
          <Drawer
            open={detailOpen()}
            onClose={() => setDetailOpen(false)}
            title={contact().name.toUpperCase()}
            side="right"
            footer={
              <Row gap={2}>
                {/* Fix 2 — Delete with confirm guard */}
                <Button
                  variant="danger"
                  leading="trash"
                  size="sm"
                  onClick={() => void handleDelete(contact())}
                >
                  DELETE
                </Button>
                <Button
                  variant="primary"
                  leading="edit"
                  size="sm"
                  onClick={() => openEdit(contact())}
                >
                  EDIT
                </Button>
              </Row>
            }
          >
            <Stack gap={4}>
              <Show when={contact().org}>
                <Field label="ORGANIZATION" value={contact().org!} />
              </Show>

              <Panel label="EMAIL ADDRESSES" flush>
                <For
                  each={contact().emails}
                  fallback={
                    <div class="px-3 py-2">
                      <Text variant="body" tone="dim">
                        No emails
                      </Text>
                    </div>
                  }
                >
                  {(email) => (
                    <ListRow
                      label={email}
                      leading="mail"
                      right={
                        <Button variant="ghost" size="sm" leading="send">
                          MAIL
                        </Button>
                      }
                    />
                  )}
                </For>
              </Panel>

              <Panel label="PHONE NUMBERS" flush>
                <For
                  each={contact().phones}
                  fallback={
                    <div class="px-3 py-2">
                      <Text variant="body" tone="dim">
                        No phone numbers
                      </Text>
                    </div>
                  }
                >
                  {(phone) => <ListRow label={phone} leading="user" />}
                </For>
              </Panel>

              <Show when={contact().notes}>
                <Panel label="NOTES">
                  <Text
                    variant="body"
                    tone="default"
                    class="whitespace-pre-wrap"
                  >
                    {contact().notes!}
                  </Text>
                </Panel>
              </Show>

              {/* Fix 4 — CardDAV status with tooltip explaining what it is */}
              <Field
                label="CARDDAV SYNC"
                value={
                  <Row gap={2} align="center">
                    <StatusFlag
                      status={contact().synced ? "nominal" : "idle"}
                      dot={contact().synced}
                    >
                      {contact().synced ? "SYNCED" : "LOCAL ONLY"}
                    </StatusFlag>
                    <Tooltip
                      label={
                        contact().synced
                          ? "Synced from your CardDAV server. Configure in Settings → Integrations."
                          : "Not synced. Configure CardDAV in Settings → Integrations to sync this contact."
                      }
                      side="top"
                    >
                      <Text
                        variant="micro"
                        tone="dim"
                        class="cursor-default select-none"
                      >
                        (?)
                      </Text>
                    </Tooltip>
                  </Row>
                }
              />
            </Stack>
          </Drawer>
        )}
      </Show>

      {/* Create/edit modal — Fix 3: validation + feedback */}
      <Modal
        open={editOpen()}
        onClose={() => setEditOpen(false)}
        title={editTargetId() ? "EDIT CONTACT" : "NEW CONTACT"}
        footer={
          <Row gap={2}>
            <Button variant="ghost" onClick={() => setEditOpen(false)}>
              CANCEL
            </Button>
            <Button variant="primary" leading="check" onClick={handleSave}>
              SAVE
            </Button>
          </Row>
        }
      >
        <Stack gap={4}>
          {/* Fix 3 — inline validation error */}
          <Show when={editError()}>
            <Row
              gap={2}
              align="center"
              class="border border-alert/40 px-3 py-2"
            >
              <Text variant="micro" tone="alert">
                {editError()}
              </Text>
            </Row>
          </Show>

          <Input
            label="FULL NAME"
            value={editName()}
            onInput={(e) => {
              setEditName(e.currentTarget.value);
              setEditError(null);
            }}
            placeholder="Full name"
          />
          <Input
            label="ORGANIZATION"
            value={editOrg()}
            onInput={(e) => setEditOrg(e.currentTarget.value)}
            placeholder="Company or org"
          />
          <Input
            label="PRIMARY EMAIL"
            type="email"
            value={editEmail()}
            onInput={(e) => {
              setEditEmail(e.currentTarget.value);
              setEditError(null);
            }}
            placeholder="email@example.com"
          />
          <Input
            label="PRIMARY PHONE"
            value={editPhone()}
            onInput={(e) => setEditPhone(e.currentTarget.value)}
            placeholder="+1 415 555 0100"
          />
          <Textarea
            label="NOTES"
            rows={4}
            value={editNotes()}
            onInput={(e) => setEditNotes(e.currentTarget.value)}
          />
        </Stack>
      </Modal>
    </Stack>
  );
}
