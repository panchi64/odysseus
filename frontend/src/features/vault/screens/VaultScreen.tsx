import { createSignal, For, onCleanup, Show, type JSX } from "solid-js";
import {
  Button,
  confirm,
  EmptyState,
  Icon,
  InfoHint,
  Input,
  ListToolbar,
  Menu,
  PageHeader,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
  toast,
  Tooltip,
} from "~/ui";
import { createListView } from "~/lib/list";
import { deleteVaultEntry, restoreVaultEntry, useVaultEntries } from "../data";
import type { VaultEntry } from "../model";

/** Rough master-password strength label for the init/unlock field. */
function passwordStrength(
  pw: string,
): { label: string; status: "alert" | "warn" | "nominal" } | null {
  if (!pw) return null;
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  if (score <= 2) return { label: "WEAK", status: "alert" };
  if (score <= 3) return { label: "FAIR", status: "warn" };
  return { label: "STRONG", status: "nominal" };
}

/** Mock master password. Phase 2 will verify against the backend. */
const MOCK_MASTER_PASSWORD = "admin1234";

export function VaultScreen(): JSX.Element {
  const entries = useVaultEntries();

  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => timers.forEach(clearTimeout));

  const [locked, setLocked] = createSignal(true);
  const [masterPassword, setMasterPassword] = createSignal("");
  const [unlockError, setUnlockError] = createSignal<string | null>(null);

  // Per-entry copy-feedback state
  const [copiedId, setCopiedId] = createSignal<string | null>(null);

  function unlock() {
    const pw = masterPassword().trim();
    if (!pw) {
      setUnlockError("Password cannot be empty.");
      return;
    }
    if (pw !== MOCK_MASTER_PASSWORD) {
      setUnlockError("INVALID MASTER PASSWORD.");
      return;
    }
    setLocked(false);
    setMasterPassword("");
    setUnlockError(null);
  }

  function lock() {
    setLocked(true);
    setMasterPassword("");
    setUnlockError(null);
    toast.success("VAULT LOCKED");
  }

  function markCopied(key: string) {
    setCopiedId(key);
    timers.push(setTimeout(() => setCopiedId(null), 2000));
  }

  function copyPassword(entry: VaultEntry) {
    void navigator.clipboard.writeText(entry.password);
    markCopied(entry.id);
    toast.success("PASSWORD COPIED TO CLIPBOARD");
  }

  function copyUsername(entry: VaultEntry) {
    void navigator.clipboard.writeText(entry.username);
    markCopied(`usr-${entry.id}`);
    toast.success("USERNAME COPIED TO CLIPBOARD");
  }

  async function handleDeleteEntry(entry: VaultEntry) {
    const ok = await confirm({
      title: `DELETE "${entry.name}"?`,
      detail:
        "This credential will be permanently removed from the vault. This action cannot be undone.",
      confirmLabel: "DELETE",
      cancelLabel: "CANCEL",
      tone: "alert",
    });
    if (!ok) return;
    deleteVaultEntry(entry.id);
    toast.success(`DELETED "${entry.name}"`, {
      action: {
        label: "UNDO",
        onClick: () => {
          restoreVaultEntry(entry);
          toast.info(`RESTORED "${entry.name}"`);
        },
      },
    });
  }

  const view = createListView({
    source: () => entries() ?? [],
    search: (e) => `${e.name} ${e.url} ${e.username}`,
    sorts: {
      name: { label: "NAME", compare: (a, b) => a.name.localeCompare(b.name) },
      url: { label: "URL", compare: (a, b) => a.url.localeCompare(b.url) },
    },
    initialSort: "name",
    initialDir: "asc",
  });

  return (
    <Stack gap={6}>
      <PageHeader
        title="PASSWORD VAULT"
        subtitle="Encrypted credential store. Agent access restricted to administrators."
        assetId="ODY-VLT-05.0 EDITION 01"
        actions={
          <Row gap={2} align="center">
            <StatusFlag status={locked() ? "alert" : "nominal"} dot>
              {locked() ? "LOCKED" : "UNLOCKED"}
            </StatusFlag>
            <Show when={!locked()}>
              <Button variant="danger" leading="lock" onClick={lock}>
                LOCK
              </Button>
            </Show>
          </Row>
        }
      />

      {/* ── LOCKED STATE ─────────────────────────────────────── */}
      <Show when={locked()}>
        <Panel label="VAULT LOCKED" state="alert">
          <Stack gap={4}>
            <Row gap={3} align="center">
              <Icon name="lock" size={24} class="text-alert" />
              <Stack gap={1}>
                <Row gap={2} align="center">
                  <Text variant="readout" tone="bright">
                    MASTER PASSWORD REQUIRED
                  </Text>
                  <InfoHint label="Credentials are encrypted at rest with a key derived from this master password. It is never stored — only its hash. The vault auto-locks on logout and stays locked until re-entered." />
                </Row>
                <Text variant="micro" tone="dim">
                  Enter the vault master password to access stored credentials.
                </Text>
              </Stack>
            </Row>
            <Input
              label="MASTER PASSWORD"
              type="password"
              value={masterPassword()}
              onInput={(e) => {
                setMasterPassword(e.currentTarget.value);
                setUnlockError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") unlock();
              }}
              invalid={unlockError() !== null}
              hint={unlockError() ?? undefined}
              placeholder="••••••••"
            />
            <Show when={passwordStrength(masterPassword())}>
              {(s) => (
                <Row gap={2} align="center">
                  <Text variant="micro" tone="dim">
                    STRENGTH
                  </Text>
                  <StatusFlag status={s().status} dot>
                    {s().label}
                  </StatusFlag>
                  <Text variant="micro" tone="dim">
                    Use 12+ characters mixing case, digits, and symbols.
                  </Text>
                </Row>
              )}
            </Show>
            <Button variant="primary" leading="key" onClick={unlock}>
              UNLOCK VAULT
            </Button>
            <Text variant="micro" tone="dim">
              If the master password is forgotten, access can be recovered
              through{" "}
              <a href="/setup" class="text-info underline underline-offset-2">
                Settings → Re-initialize vault
              </a>
              .
            </Text>
            <Text variant="micro" tone="dim">
              Agent access to vault credentials is restricted to admin-role
              sessions only.
            </Text>
          </Stack>
        </Panel>
      </Show>

      {/* ── UNLOCKED STATE ───────────────────────────────────── */}
      <Show when={!locked()}>
        <Panel label="CREDENTIALS" flush>
          <div class="border-b border-line p-3">
            <ListToolbar
              query={view.query()}
              onQueryChange={view.setQuery}
              placeholder="Search by name or URL…"
              sortKey={view.sortKey()}
              sortOptions={view.sortOptions}
              onSortChange={view.setSort}
              dir={view.dir()}
              onToggleDir={view.toggleDir}
              count={view.count()}
              total={view.total()}
            />
          </div>
          <For each={view.items()}>
            {(entry) => (
              <div class="border-b border-line last:border-b-0">
                <div class="flex items-start justify-between gap-3 px-3 py-3">
                  <Stack gap={1} class="min-w-0 flex-1">
                    <Row gap={2} align="center">
                      <Icon name="key" size={12} class="text-dim shrink-0" />
                      <Text variant="label" tone="bright" class="truncate">
                        {entry.name}
                      </Text>
                    </Row>
                    <Text variant="micro" tone="dim" class="truncate">
                      {entry.url}
                    </Text>
                    <Row gap={2} align="center" class="mt-1">
                      <Text variant="micro" tone="dim">
                        {entry.username}
                      </Text>
                      <Tooltip
                        label={
                          copiedId() === `usr-${entry.id}`
                            ? "Copied!"
                            : "Copy username"
                        }
                      >
                        <button
                          type="button"
                          class="text-dim transition-colors hover:text-bright"
                          onClick={() => copyUsername(entry)}
                        >
                          <Icon
                            name={
                              copiedId() === `usr-${entry.id}`
                                ? "check"
                                : "file"
                            }
                            size={10}
                          />
                        </button>
                      </Tooltip>
                    </Row>
                  </Stack>
                  <Row gap={2} align="center" class="shrink-0">
                    {/* Password field — copy-only; no plaintext render in DOM */}
                    <div class="flex items-center gap-2 border border-line bg-raised px-2 py-1">
                      <Text
                        variant="micro"
                        tone="dim"
                        class="font-mono w-36 truncate"
                      >
                        ••••••••••••
                      </Text>
                      <Tooltip
                        label={
                          copiedId() === entry.id ? "Copied!" : "Copy password"
                        }
                      >
                        <button
                          type="button"
                          class="text-dim transition-colors hover:text-bright"
                          onClick={() => copyPassword(entry)}
                        >
                          <Icon
                            name={copiedId() === entry.id ? "check" : "file"}
                            size={12}
                          />
                        </button>
                      </Tooltip>
                    </div>
                    <Menu
                      trigger={
                        <Button variant="ghost" size="sm" leading="menu" />
                      }
                      items={[
                        {
                          label: "DELETE ENTRY",
                          icon: "trash",
                          danger: true,
                          onSelect: () => void handleDeleteEntry(entry),
                        },
                      ]}
                      align="right"
                    />
                  </Row>
                </div>
              </div>
            )}
          </For>
          <Show when={view.items().length === 0}>
            <EmptyState
              icon="key"
              message="NO CREDENTIALS"
              hint={
                view.isFiltered()
                  ? "No entries match your search."
                  : "No vault entries yet."
              }
            />
          </Show>
        </Panel>
      </Show>
    </Stack>
  );
}
