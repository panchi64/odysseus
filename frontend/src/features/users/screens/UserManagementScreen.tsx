import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import { createStore, produce } from "solid-js/store";
import {
  Button,
  Checkbox,
  Divider,
  Drawer,
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

  // Modal: create user
  const [createOpen, setCreateOpen] = createSignal(false);
  const [newName, setNewName] = createSignal("");
  const [newPassword, setNewPassword] = createSignal("");
  const [newIsAdmin, setNewIsAdmin] = createSignal(false);

  // Modal: delete confirm
  const [deleteTarget, setDeleteTarget] = createSignal<ManagedUser | null>(
    null,
  );

  function seed(list: ManagedUser[]) {
    if (!seeded) {
      seeded = true;
      setUsers(list.map((u) => ({ ...u })));
    }
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

  function createUser() {
    if (!newName().trim()) return;
    const id = `u-${String(users.length + 1).padStart(3, "0")}`;
    const user: ManagedUser = {
      id,
      name: newName().toUpperCase(),
      isAdmin: newIsAdmin(),
      lastActiveAt: new Date().toISOString(),
      privileges: [],
      status: "active",
    };
    setUsers((u) => [...u, user]);
    setNewName("");
    setNewPassword("");
    setNewIsAdmin(false);
    setCreateOpen(false);
  }

  function deleteUser(id: string) {
    setUsers((u) => u.filter((x) => x.id !== id));
    setDeleteTarget(null);
  }

  function toggleUserStatus(id: string) {
    setUsers(
      (u) => u.id === id,
      produce((u) => {
        u.status = u.status === "active" ? "disabled" : "active";
      }),
    );
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
                        onSelect: () => setDrawerUser({ ...user }),
                      },
                      {
                        label:
                          user.status === "active"
                            ? "DISABLE USER"
                            : "ENABLE USER",
                        icon: user.status === "active" ? "close" : "check",
                        onSelect: () => toggleUserStatus(user.id),
                      },
                      {
                        label: "DELETE USER",
                        icon: "trash",
                        danger: true,
                        onSelect: () => setDeleteTarget(user),
                      },
                    ]}
                  />
                </Row>
              }
            />
          )}
        </For>
        <Show when={users.length === 0}>
          <div class="p-4">
            <Text variant="body" tone="dim">
              No users registered.
            </Text>
          </div>
        </Show>
      </Panel>

      {/* ── PRIVILEGE EDITOR DRAWER ──────────────────────────── */}
      <Drawer
        open={drawerUser() !== null}
        onClose={() => setDrawerUser(null)}
        title={`PRIVILEGES · ${drawerUser()?.name ?? ""}`}
        footer={
          <Button variant="primary" onClick={() => setDrawerUser(null)}>
            CLOSE
          </Button>
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
        onClose={() => setCreateOpen(false)}
        title="CREATE USER"
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              CANCEL
            </Button>
            <Button
              variant="primary"
              onClick={createUser}
              disabled={!newName().trim()}
            >
              CREATE
            </Button>
          </>
        }
      >
        <Stack gap={3}>
          <Input
            label="USERNAME"
            value={newName()}
            onInput={(e) => setNewName(e.currentTarget.value)}
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

      {/* ── DELETE CONFIRM MODAL ─────────────────────────────── */}
      <Modal
        open={deleteTarget() !== null}
        onClose={() => setDeleteTarget(null)}
        title="DELETE USER"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
              CANCEL
            </Button>
            <Button
              variant="danger"
              onClick={() => deleteTarget() && deleteUser(deleteTarget()!.id)}
            >
              DELETE
            </Button>
          </>
        }
      >
        <Stack gap={2}>
          <Text variant="body" tone="default">
            Permanently delete{" "}
            <Text as="span" tone="bright">
              {deleteTarget()?.name}
            </Text>
            ?
          </Text>
          <Text variant="micro" tone="dim">
            This action cannot be undone. All user data and sessions will be
            removed.
          </Text>
        </Stack>
      </Modal>
    </Stack>
  );
}
