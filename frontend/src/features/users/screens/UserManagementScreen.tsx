import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import { createStore, produce } from "solid-js/store";
import {
  Button,
  Checkbox,
  Divider,
  Drawer,
  EmptyState,
  InfoHint,
  Input,
  ListRow,
  ListToolbar,
  LoadingText,
  Menu,
  Modal,
  PageHeader,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
  Toggle,
  confirm,
  copyToClipboard,
  toast,
  type Status,
} from "~/ui";
import { createListView } from "~/lib/list";
import { relativeTime } from "~/lib/format";
import { useUsers } from "../data";
import type { ManagedUser, Privilege } from "../model";
import { ALL_PRIVILEGES, PRIVILEGE_LEGEND } from "../model";

const userStatus = (u: ManagedUser): Status => {
  if (u.status === "disabled") return "idle";
  if (u.isAdmin) return "nominal";
  return "info";
};

/** Generate a mock initial password (diegetic — Phase 2 returns the real one). */
function generatePassword(): string {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789abcdefghijkmnpqrstuvwxyz";
  let out = "";
  for (let i = 0; i < 16; i++) {
    out += chars[Math.floor(Math.random() * chars.length)];
  }
  return out;
}

export function UserManagementScreen(): JSX.Element {
  const usersResource = useUsers();

  // Local mutable list
  const [users, setUsers] = createStore<ManagedUser[]>([]);
  let seeded = false;

  const view = createListView<ManagedUser>({
    source: () => users,
    search: (u) => u.name,
    sorts: {
      name: {
        label: "NAME",
        compare: (a, b) => a.name.localeCompare(b.name),
      },
      recent: {
        label: "LAST ACTIVE",
        compare: (a, b) => a.lastActiveAt.localeCompare(b.lastActiveAt),
      },
    },
    initialSort: "name",
    id: (u) => u.id,
  });

  // Drawer: privilege editor
  const [drawerUser, setDrawerUser] = createSignal<ManagedUser | null>(null);
  // Track privileges at the time the drawer was opened so REVERT works
  const [savedPrivileges, setSavedPrivileges] = createSignal<Privilege[]>([]);

  // Modal: create user
  const [createOpen, setCreateOpen] = createSignal(false);
  const [newName, setNewName] = createSignal("");
  const [newPassword, setNewPassword] = createSignal("");
  const [newIsAdmin, setNewIsAdmin] = createSignal(false);
  const [createError, setCreateError] = createSignal<string | null>(null);
  const [createPending, setCreatePending] = createSignal(false);

  // Modal: password handoff (shown after create or reset)
  const [handoff, setHandoff] = createSignal<{
    name: string;
    password: string;
    title: string;
  } | null>(null);

  function seed(list: ManagedUser[]) {
    if (!seeded) {
      seeded = true;
      setUsers(list.map((u) => ({ ...u })));
    }
  }

  function openDrawer(user: ManagedUser) {
    const snapshot = { ...user, privileges: [...user.privileges] };
    setDrawerUser(snapshot);
    setSavedPrivileges([...user.privileges]);
  }

  function closeDrawer() {
    setDrawerUser(null);
    setSavedPrivileges([]);
  }

  function revertPrivileges() {
    const u = drawerUser();
    if (!u) return;
    // Restore in-store privileges to the saved snapshot
    setUsers(
      (x) => x.id === u.id,
      produce((x) => {
        x.privileges = [...savedPrivileges()];
      }),
    );
    // Update the drawer view
    setDrawerUser({ ...u, privileges: [...savedPrivileges()] });
    toast.info("PRIVILEGES REVERTED");
  }

  function togglePrivilege(userId: string, priv: Privilege) {
    setUsers(
      (u) => u.id === userId,
      produce((u) => {
        const idx = u.privileges.indexOf(priv);
        if (idx >= 0) u.privileges.splice(idx, 1);
        else u.privileges.push(priv);
      }),
    );
    // Keep drawer user in sync
    const updated = users.find((u) => u.id === userId);
    if (updated) setDrawerUser({ ...updated });
  }

  function hasUnsavedPrivilegeChanges(): boolean {
    const u = drawerUser();
    if (!u) return false;
    const saved = savedPrivileges();
    if (u.privileges.length !== saved.length) return true;
    return u.privileges.some((p) => !saved.includes(p));
  }

  async function createUser() {
    const name = newName().trim();
    if (!name) {
      setCreateError("USERNAME IS REQUIRED");
      return;
    }
    setCreateError(null);
    setCreatePending(true);
    // Phase 1: simulate async work
    await Promise.resolve();
    const id = `u-${String(users.length + 1).padStart(3, "0")}`;
    const password = newPassword().trim() || generatePassword();
    const user: ManagedUser = {
      id,
      name: name.toUpperCase(),
      isAdmin: newIsAdmin(),
      lastActiveAt: new Date().toISOString(),
      privileges: [],
      status: "active",
    };
    setUsers((u) => [...u, user]);
    setNewName("");
    setNewPassword("");
    setNewIsAdmin(false);
    setCreatePending(false);
    setCreateOpen(false);
    toast.success(`CREATED USER ${user.name}`);
    // Surface the initial password for handoff
    setHandoff({
      name: user.name,
      password,
      title: "USER CREATED",
    });
  }

  function resetPassword(user: ManagedUser) {
    const password = generatePassword();
    setHandoff({
      name: user.name,
      password,
      title: "PASSWORD RESET",
    });
    toast.success(`PASSWORD RESET FOR ${user.name}`);
  }

  async function handleDeleteUser(user: ManagedUser) {
    const ok = await confirm({
      title: `DELETE "${user.name}"?`,
      detail:
        "This action cannot be undone. All user data and sessions will be removed.",
      confirmLabel: "DELETE",
      cancelLabel: "CANCEL",
      tone: "alert",
    });
    if (!ok) return;
    const deleted = { ...user };
    setUsers((u) => u.filter((x) => x.id !== deleted.id));
    toast.success(`DELETED USER ${deleted.name}`, {
      action: {
        label: "UNDO",
        onClick: () => {
          setUsers((u) => [...u, deleted]);
          toast.info(`RESTORED USER ${deleted.name}`);
        },
      },
    });
  }

  function toggleUserStatus(user: ManagedUser) {
    const nextStatus = user.status === "active" ? "disabled" : "active";
    setUsers(
      (u) => u.id === user.id,
      produce((u) => {
        u.status = nextStatus;
      }),
    );
    toast.success(
      `USER ${user.name} ${nextStatus === "active" ? "ENABLED" : "DISABLED"}`,
    );
  }

  // ── Bulk actions ────────────────────────────────────────────
  function bulkDisable() {
    const targets = view.selectedItems().filter((u) => u.status === "active");
    if (targets.length === 0) {
      toast.info("SELECTED USERS ALREADY DISABLED");
      view.clearSelection();
      return;
    }
    const ids = new Set(targets.map((u) => u.id));
    setUsers(
      (u) => ids.has(u.id),
      produce((u) => {
        u.status = "disabled";
      }),
    );
    toast.success(`DISABLED ${targets.length} USER(S)`);
    view.clearSelection();
  }

  async function bulkDelete() {
    const targets = view.selectedItems();
    if (targets.length === 0) return;
    const ok = await confirm({
      title: `DELETE ${targets.length} USER(S)?`,
      detail:
        "This action cannot be undone. All selected users and their sessions will be removed.",
      confirmLabel: "DELETE",
      cancelLabel: "CANCEL",
      tone: "alert",
    });
    if (!ok) return;
    const removed = targets.map((u) => ({ ...u }));
    const ids = new Set(targets.map((u) => u.id));
    setUsers((u) => u.filter((x) => !ids.has(x.id)));
    view.clearSelection();
    toast.success(`DELETED ${removed.length} USER(S)`, {
      action: {
        label: "UNDO",
        onClick: () => {
          setUsers((u) => [...u, ...removed]);
          toast.info(`RESTORED ${removed.length} USER(S)`);
        },
      },
    });
  }

  function handleCloseCreateModal() {
    setCreateError(null);
    setNewName("");
    setNewPassword("");
    setNewIsAdmin(false);
    setCreateOpen(false);
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="USER MANAGEMENT"
        subtitle="Manage workspace users, roles, and access privileges."
        assetId="ODY-ADM-02.0 EDITION 01"
        actions={
          <Button
            variant="primary"
            leading="plus"
            onClick={() => setCreateOpen(true)}
          >
            CREATE USER
          </Button>
        }
      />

      <Suspense fallback={<LoadingText />}>
        <Show when={usersResource()} keyed>
          {(list) => {
            seed(list);
            return null;
          }}
        </Show>
      </Suspense>

      <Panel label="REGISTERED USERS" flush>
        <div class="border-b border-line p-3">
          <ListToolbar
            query={view.query()}
            onQueryChange={view.setQuery}
            placeholder="Search users…"
            sortKey={view.sortKey()}
            sortOptions={view.sortOptions}
            onSortChange={view.setSort}
            dir={view.dir()}
            onToggleDir={view.toggleDir}
            count={view.count()}
            total={view.total()}
            selectedCount={view.selectedCount()}
            onClearSelection={view.clearSelection}
            bulkActions={
              <>
                <Button
                  variant="default"
                  size="sm"
                  leading="close"
                  onClick={bulkDisable}
                >
                  DISABLE
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  leading="trash"
                  onClick={bulkDelete}
                >
                  DELETE
                </Button>
              </>
            }
          />
        </div>

        <Show
          when={view.items().length}
          fallback={
            <EmptyState
              icon="users"
              message="NO USERS"
              hint={
                view.isFiltered()
                  ? "No users match your search."
                  : "No users registered."
              }
            />
          }
        >
          <For each={view.items()}>
            {(user) => (
              <ListRow
                label={user.name}
                selectable
                selected={view.isSelected(user.id)}
                onClick={() => view.toggleOne(user.id)}
                class={user.status === "disabled" ? "opacity-50" : undefined}
                right={
                  <Row gap={2} align="center">
                    <Text variant="micro" tone="dim">
                      {relativeTime(user.lastActiveAt)}
                    </Text>
                    <StatusFlag status={userStatus(user)} dot>
                      {user.isAdmin ? "ADMIN" : user.status.toUpperCase()}
                    </StatusFlag>
                    <Menu
                      trigger={
                        <Button variant="ghost" size="sm" leading="settings" />
                      }
                      items={[
                        {
                          label: "EDIT PRIVILEGES",
                          icon: "key",
                          onSelect: () => openDrawer(user),
                        },
                        {
                          label: "RESET PASSWORD",
                          icon: "refresh",
                          onSelect: () => resetPassword(user),
                        },
                        {
                          label:
                            user.status === "active"
                              ? "DISABLE USER"
                              : "ENABLE USER",
                          icon: user.status === "active" ? "close" : "check",
                          onSelect: () => toggleUserStatus(user),
                        },
                        {
                          label: "DELETE USER",
                          icon: "trash",
                          danger: true,
                          onSelect: () => handleDeleteUser(user),
                        },
                      ]}
                    />
                  </Row>
                }
              />
            )}
          </For>
        </Show>
      </Panel>

      {/* ── PRIVILEGE EDITOR DRAWER ──────────────────────────── */}
      <Drawer
        open={drawerUser() !== null}
        onClose={closeDrawer}
        title={`PRIVILEGES · ${drawerUser()?.name ?? ""}`}
        footer={
          <Row gap={2} justify="between">
            <Show when={hasUnsavedPrivilegeChanges()}>
              <Button variant="ghost" onClick={revertPrivileges}>
                REVERT
              </Button>
            </Show>
            <Button variant="primary" onClick={closeDrawer}>
              CLOSE
            </Button>
          </Row>
        }
      >
        <Show when={drawerUser()} keyed>
          {(u) => (
            <Stack gap={4}>
              <Row gap={2} align="center">
                <StatusFlag status={userStatus(u)} dot>
                  {u.isAdmin ? "ADMINISTRATOR" : "USER"}
                </StatusFlag>
                <Text variant="micro" tone="dim">
                  ID: {u.id}
                </Text>
              </Row>
              <Divider />
              <Stack gap={3}>
                <Text variant="label" tone="dim">
                  ACCESS PRIVILEGES
                </Text>
                <For each={ALL_PRIVILEGES}>
                  {(priv) => (
                    <Row align="center" justify="between">
                      <Row gap={1} align="center">
                        <Text variant="label" tone="default">
                          {priv.toUpperCase()}
                        </Text>
                        <InfoHint label={PRIVILEGE_LEGEND[priv]} />
                      </Row>
                      <Toggle
                        checked={u.privileges.includes(priv)}
                        onChange={() => togglePrivilege(u.id, priv)}
                      />
                    </Row>
                  )}
                </For>
              </Stack>
            </Stack>
          )}
        </Show>
      </Drawer>

      {/* ── CREATE USER MODAL ────────────────────────────────── */}
      <Modal
        open={createOpen()}
        onClose={handleCloseCreateModal}
        title="CREATE USER"
        footer={
          <>
            <Button
              variant="ghost"
              onClick={handleCloseCreateModal}
              disabled={createPending()}
            >
              CANCEL
            </Button>
            <Button
              variant="primary"
              onClick={createUser}
              disabled={!newName().trim() || createPending()}
            >
              {createPending() ? "CREATING…" : "CREATE"}
            </Button>
          </>
        }
      >
        <Stack gap={3}>
          <Show when={createError()}>
            {(msg) => (
              <Text variant="micro" tone="alert">
                {msg()}
              </Text>
            )}
          </Show>
          <Input
            label="USERNAME"
            value={newName()}
            onInput={(e) => {
              setNewName(e.currentTarget.value);
              if (createError()) setCreateError(null);
            }}
            placeholder="NEWUSER"
          />
          <Input
            label="PASSWORD"
            type="password"
            value={newPassword()}
            onInput={(e) => setNewPassword(e.currentTarget.value)}
            placeholder="LEAVE BLANK TO AUTO-GENERATE"
            hint="If blank, an initial password is generated and shown once."
          />
          <Checkbox
            label="GRANT ADMINISTRATOR ROLE"
            checked={newIsAdmin()}
            onChange={setNewIsAdmin}
          />
        </Stack>
      </Modal>

      {/* ── PASSWORD HANDOFF MODAL (create / reset) ──────────── */}
      <Modal
        open={handoff() !== null}
        onClose={() => setHandoff(null)}
        title={handoff()?.title ?? ""}
        footer={
          <Button variant="primary" onClick={() => setHandoff(null)}>
            DONE
          </Button>
        }
      >
        <Show when={handoff()} keyed>
          {(h) => (
            <Stack gap={3}>
              <Text variant="body" tone="dim">
                Initial password for{" "}
                <Text variant="label" tone="bright" as="span">
                  {h.name}
                </Text>
                . This is shown only once — give it to the user securely and
                have them change it on first sign-in.
              </Text>
              <div class="flex items-center justify-between gap-2 border border-line bg-raised px-3 py-2">
                <Text
                  variant="readout"
                  tone="bright"
                  class="font-mono tracking-wide break-all"
                >
                  {h.password}
                </Text>
                <Button
                  variant="ghost"
                  size="sm"
                  leading="copy"
                  onClick={() => copyToClipboard(h.password, "Password")}
                >
                  COPY
                </Button>
              </div>
            </Stack>
          )}
        </Show>
      </Modal>
    </Stack>
  );
}
