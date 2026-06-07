import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import { createStore, produce } from "solid-js/store";
import {
  Button,
  Checkbox,
  Divider,
  Drawer,
  EmptyState,
  Input,
  ListRow,
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
  toast,
  type Status,
} from "~/ui";
import { relativeTime } from "~/lib/format";
import { useUsers } from "../data";
import type { ManagedUser, Privilege } from "../model";
import { ALL_PRIVILEGES } from "../model";

const userStatus = (u: ManagedUser): Status => {
  if (u.status === "disabled") return "idle";
  if (u.isAdmin) return "nominal";
  return "info";
};

export function UserManagementScreen(): JSX.Element {
  const usersResource = useUsers();

  // Local mutable list
  const [users, setUsers] = createStore<ManagedUser[]>([]);
  let seeded = false;

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

      <Panel
        label="REGISTERED USERS"
        meta={
          <Text variant="micro" tone="dim">
            {users.length} TOTAL
          </Text>
        }
        flush
      >
        <For each={users}>
          {(user, i) => (
            <ListRow
              label={user.name}
              leading="user"
              flush={i() === users.length - 1}
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
        <Show when={users.length === 0}>
          <EmptyState message="NO USERS REGISTERED" />
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
                      <Text variant="label" tone="default">
                        {priv.toUpperCase()}
                      </Text>
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
            placeholder="••••••••"
          />
          <Checkbox
            label="GRANT ADMINISTRATOR ROLE"
            checked={newIsAdmin()}
            onChange={setNewIsAdmin}
          />
        </Stack>
      </Modal>
    </Stack>
  );
}
