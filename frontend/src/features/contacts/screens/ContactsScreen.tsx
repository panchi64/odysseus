import {
  createMemo,
  createSignal,
  For,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import {
  Button,
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
  Row,
  Stack,
  StatusFlag,
  Text,
  Textarea,
} from "~/ui";
import { useContacts } from "../data";
import type { Contact } from "../model";

export function ContactsScreen(): JSX.Element {
  const contacts = useContacts();
  const [search, setSearch] = createSignal("");
  const [selectedId, setSelectedId] = createSignal<string | null>(null);
  const [detailOpen, setDetailOpen] = createSignal(false);
  const [editOpen, setEditOpen] = createSignal(false);

  // Edit form state
  const [editName, setEditName] = createSignal("");
  const [editOrg, setEditOrg] = createSignal("");
  const [editEmail, setEditEmail] = createSignal("");
  const [editPhone, setEditPhone] = createSignal("");
  const [editNotes, setEditNotes] = createSignal("");

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

  return (
    <Stack gap={6}>
      <PageHeader
        title="CONTACTS"
        subtitle="CardDAV-synced address book."
        assetId="COMM-CTC-01.0"
        actions={
          <Row gap={2}>
            <Button variant="ghost" leading="refresh" size="sm">
              SYNC
            </Button>
            <Button variant="primary" leading="plus" onClick={() => openEdit()}>
              NEW CONTACT
            </Button>
          </Row>
        }
      />

      <Suspense fallback={<LoadingText label="LOADING CONTACTS" />}>
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
              value: String(totalCount() - syncedCount()),
              tone: totalCount() - syncedCount() > 0 ? "warn" : "dim",
            },
            { label: "SHOWING", value: String(filtered().length) },
          ]}
        />
      </Suspense>

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

      <Suspense fallback={<LoadingText label="LOADING" />}>
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
      </Suspense>

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
                <Button variant="danger" leading="trash" size="sm">
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

              <Field
                label="CARDDAV SYNC"
                value={
                  <StatusFlag
                    status={contact().synced ? "nominal" : "idle"}
                    dot={contact().synced}
                  >
                    {contact().synced ? "SYNCED" : "LOCAL ONLY"}
                  </StatusFlag>
                }
              />
            </Stack>
          </Drawer>
        )}
      </Show>

      {/* Create/edit modal */}
      <Modal
        open={editOpen()}
        onClose={() => setEditOpen(false)}
        title={editName() ? "EDIT CONTACT" : "NEW CONTACT"}
        footer={
          <Row gap={2}>
            <Button variant="ghost" onClick={() => setEditOpen(false)}>
              CANCEL
            </Button>
            <Button
              variant="primary"
              leading="check"
              onClick={() => setEditOpen(false)}
            >
              SAVE
            </Button>
          </Row>
        }
      >
        <Stack gap={4}>
          <Input
            label="FULL NAME"
            value={editName()}
            onInput={(e) => setEditName(e.currentTarget.value)}
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
            onInput={(e) => setEditEmail(e.currentTarget.value)}
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
