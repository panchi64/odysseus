import {
  createSignal,
  For,
  onCleanup,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import {
  Button,
  confirm,
  EmptyState,
  Icon,
  InfoHint,
  Input,
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
  toast,
  Tooltip,
} from "~/ui";
import { isApiError } from "~/lib/api";
import { createListView } from "~/lib/list";
import {
  configureVault,
  createVaultEntry,
  deleteVaultEntry,
  lockVault,
  unlockVault,
  useVaultEntries,
  useVaultState,
} from "../data";
import type { VaultEntry } from "../model";

/** Rough passphrase-strength label for the setup field. Presentation only — the
 *  backend neither enforces nor sees this. */
function passphraseStrength(
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

function errorText(err: unknown, fallback: string): string {
  return isApiError(err) ? err.detail : fallback;
}

const EMPTY_DRAFT = { name: "", username: "", url: "", password: "" };

export function VaultScreen(): JSX.Element {
  const state = useVaultState();
  const locked = () => state()?.locked ?? true;
  const configured = () => state()?.configured ?? false;
  const entries = useVaultEntries(() => !locked());

  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => timers.forEach(clearTimeout));

  const [passphrase, setPassphrase] = createSignal("");
  const [passphraseError, setPassphraseError] = createSignal<string | null>(
    null,
  );
  const [busy, setBusy] = createSignal(false);

  // Per-entry copy-feedback state
  const [copiedId, setCopiedId] = createSignal<string | null>(null);

  // Add-entry form
  const [addOpen, setAddOpen] = createSignal(false);
  const [draft, setDraft] = createSignal({ ...EMPTY_DRAFT });
  const [addError, setAddError] = createSignal<string | null>(null);

  function resetPassphraseField() {
    setPassphrase("");
    setPassphraseError(null);
  }

  async function submitPassphrase() {
    const pw = passphrase();
    if (!pw) {
      setPassphraseError("Passphrase cannot be empty.");
      return;
    }
    setBusy(true);
    try {
      if (configured()) {
        await unlockVault(pw);
        toast.success("VAULT UNLOCKED");
      } else {
        await configureVault(pw);
        toast.success("VAULT CREATED");
      }
      resetPassphraseField();
    } catch (err) {
      setPassphraseError(
        errorText(
          err,
          configured() ? "Could not unlock the vault." : "Could not create it.",
        ).toUpperCase(),
      );
    } finally {
      setBusy(false);
    }
  }

  async function lock() {
    try {
      await lockVault();
      resetPassphraseField();
      toast.success("VAULT LOCKED");
    } catch (err) {
      toast.error(errorText(err, "Could not lock the vault."));
    }
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

  async function submitEntry() {
    const input = draft();
    if (!input.name.trim()) {
      setAddError("Name is required.");
      return;
    }
    setBusy(true);
    try {
      await createVaultEntry({ ...input, name: input.name.trim() });
      setDraft({ ...EMPTY_DRAFT });
      setAddError(null);
      setAddOpen(false);
      toast.success(`SAVED "${input.name.trim()}"`);
    } catch (err) {
      setAddError(errorText(err, "Could not save the credential."));
    } finally {
      setBusy(false);
    }
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
    try {
      await deleteVaultEntry(entry.id);
      toast.success(`DELETED "${entry.name}"`);
    } catch (err) {
      toast.error(errorText(err, "Could not delete the credential."));
    }
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
        subtitle="Encrypted credential store. Agent reads require explicit approval."
        assetId="ODY-VLT-05.0 EDITION 01"
        actions={
          <Row gap={2} align="center">
            <StatusFlag status={locked() ? "alert" : "nominal"} dot>
              {locked() ? "LOCKED" : "UNLOCKED"}
            </StatusFlag>
            <Show when={!locked()}>
              <Button
                variant="danger"
                leading="lock"
                onClick={() => void lock()}
              >
                LOCK
              </Button>
            </Show>
          </Row>
        }
      />

      <Suspense fallback={<LoadingText />}>
        {/* ── LOCKED / UNCONFIGURED STATE ────────────────────── */}
        <Show when={locked()}>
          <Panel
            label={configured() ? "VAULT LOCKED" : "VAULT NOT SET UP"}
            state="alert"
          >
            <Stack gap={4}>
              <Row gap={3} align="center">
                <Icon name="lock" size={24} class="text-alert" />
                <Stack gap={1}>
                  <Row gap={2} align="center">
                    <Text variant="readout" tone="bright">
                      {configured()
                        ? "VAULT PASSPHRASE REQUIRED"
                        : "CHOOSE A VAULT PASSPHRASE"}
                    </Text>
                    <InfoHint label="Credentials are sealed with a key derived from this passphrase, which is never stored and never leaves memory. It is separate from your login password: unlocking the app does not unlock the vault, and restarting re-locks it." />
                  </Row>
                  <Text variant="micro" tone="dim">
                    {configured()
                      ? "Enter the vault passphrase to access stored credentials."
                      : "No vault exists yet. The passphrase you choose here cannot be recovered."}
                  </Text>
                </Stack>
              </Row>
              <Input
                label={
                  configured() ? "VAULT PASSPHRASE" : "NEW VAULT PASSPHRASE"
                }
                type="password"
                value={passphrase()}
                onInput={(e) => {
                  setPassphrase(e.currentTarget.value);
                  setPassphraseError(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void submitPassphrase();
                }}
                invalid={passphraseError() !== null}
                hint={passphraseError() ?? undefined}
                placeholder="••••••••"
              />
              <Show when={!configured() && passphraseStrength(passphrase())}>
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
              <Button
                variant="primary"
                leading="key"
                disabled={busy()}
                onClick={() => void submitPassphrase()}
              >
                {configured() ? "UNLOCK VAULT" : "CREATE VAULT"}
              </Button>
              <Text variant="micro" tone="dim">
                Agent access to vault credentials pauses for your approval on
                every read.
              </Text>
            </Stack>
          </Panel>
        </Show>

        {/* ── UNLOCKED STATE ───────────────────────────────────── */}
        <Show when={!locked()}>
          <Panel label="CREDENTIALS" flush>
            <div class="border-b border-line p-3">
              <Row gap={3} align="center" justify="between">
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
                <Button
                  variant="primary"
                  size="sm"
                  leading="plus"
                  onClick={() => {
                    setDraft({ ...EMPTY_DRAFT });
                    setAddError(null);
                    setAddOpen(true);
                  }}
                >
                  ADD
                </Button>
              </Row>
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
                            copiedId() === entry.id
                              ? "Copied!"
                              : "Copy password"
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
                    : "No vault entries yet — use ADD to store one."
                }
              />
            </Show>
          </Panel>
        </Show>
      </Suspense>

      {/* ── ADD ENTRY ────────────────────────────────────────── */}
      <Modal
        open={addOpen()}
        onClose={() => setAddOpen(false)}
        title="ADD CREDENTIAL"
        footer={
          <>
            <Button variant="ghost" onClick={() => setAddOpen(false)}>
              CANCEL
            </Button>
            <Button
              variant="primary"
              disabled={busy()}
              onClick={() => void submitEntry()}
            >
              SAVE
            </Button>
          </>
        }
      >
        <Stack gap={3}>
          <Input
            label="NAME"
            value={draft().name}
            onInput={(e) => {
              setDraft({ ...draft(), name: e.currentTarget.value });
              setAddError(null);
            }}
            invalid={addError() !== null}
            hint={addError() ?? undefined}
            placeholder="Production database"
          />
          <Input
            label="URL"
            value={draft().url}
            onInput={(e) =>
              setDraft({ ...draft(), url: e.currentTarget.value })
            }
            placeholder="https://…"
          />
          <Input
            label="USERNAME"
            value={draft().username}
            onInput={(e) =>
              setDraft({ ...draft(), username: e.currentTarget.value })
            }
          />
          <Input
            label="PASSWORD"
            type="password"
            value={draft().password}
            onInput={(e) =>
              setDraft({ ...draft(), password: e.currentTarget.value })
            }
            placeholder="••••••••"
          />
        </Stack>
      </Modal>
    </Stack>
  );
}
