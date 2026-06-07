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
  Icon,
  Input,
  LoadingText,
  PageHeader,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
  Tooltip,
} from "~/ui";
import { useVaultEntries } from "../data";
import type { VaultEntry } from "../model";

export function VaultScreen(): JSX.Element {
  const entries = useVaultEntries();

  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => timers.forEach(clearTimeout));

  const [locked, setLocked] = createSignal(true);
  const [masterPassword, setMasterPassword] = createSignal("");
  const [unlockError, setUnlockError] = createSignal(false);

  // Per-entry reveal state
  const [revealed, setRevealed] = createSignal<Set<string>>(new Set());
  const [copiedId, setCopiedId] = createSignal<string | null>(null);

  function unlock() {
    if (!masterPassword().trim()) {
      setUnlockError(true);
      return;
    }
    // Mock: any non-empty password unlocks
    setLocked(false);
    setMasterPassword("");
    setUnlockError(false);
  }

  function lock() {
    setLocked(true);
    setRevealed(new Set<string>());
    setMasterPassword("");
  }

  function toggleReveal(id: string) {
    setRevealed((s) => {
      const next = new Set<string>(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function copyPassword(entry: VaultEntry) {
    void navigator.clipboard.writeText(entry.password);
    setCopiedId(entry.id);
    timers.push(setTimeout(() => setCopiedId(null), 2000));
  }

  function copyUsername(entry: VaultEntry) {
    void navigator.clipboard.writeText(entry.username);
    setCopiedId(`usr-${entry.id}`);
    timers.push(setTimeout(() => setCopiedId(null), 2000));
  }

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
                <Text variant="readout" tone="bright">
                  MASTER PASSWORD REQUIRED
                </Text>
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
                setUnlockError(false);
              }}
              invalid={unlockError()}
              hint={unlockError() ? "Password cannot be empty." : undefined}
              placeholder="••••••••"
            />
            <Button variant="primary" leading="key" onClick={unlock}>
              UNLOCK VAULT
            </Button>
            <Text variant="micro" tone="dim">
              Agent access to vault credentials is restricted to admin-role
              sessions only.
            </Text>
          </Stack>
        </Panel>
      </Show>

      {/* ── UNLOCKED STATE ───────────────────────────────────── */}
      <Show when={!locked()}>
        <Suspense fallback={<LoadingText />}>
          <Panel
            label="CREDENTIALS"
            meta={
              <Text variant="micro" tone="dim">
                {entries()?.length ?? 0} ENTRIES
              </Text>
            }
            flush
          >
            <For each={entries()}>
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
                      <div class="flex items-center gap-2 border border-line bg-raised px-2 py-1">
                        <Text
                          variant="micro"
                          tone={revealed().has(entry.id) ? "bright" : "dim"}
                          class="font-mono w-36 truncate"
                        >
                          {revealed().has(entry.id)
                            ? entry.password
                            : "••••••••••••"}
                        </Text>
                        <button
                          type="button"
                          class="text-dim transition-colors hover:text-bright"
                          onClick={() => toggleReveal(entry.id)}
                        >
                          <Icon name="eye" size={12} />
                        </button>
                      </div>
                      <Tooltip
                        label={
                          copiedId() === entry.id ? "Copied!" : "Copy password"
                        }
                      >
                        <Button
                          variant="ghost"
                          size="sm"
                          leading={copiedId() === entry.id ? "check" : "file"}
                          onClick={() => copyPassword(entry)}
                        />
                      </Tooltip>
                    </Row>
                  </div>
                </div>
              )}
            </For>
            <Show when={(entries()?.length ?? 0) === 0}>
              <div class="p-4">
                <Text variant="body" tone="dim">
                  No vault entries.
                </Text>
              </div>
            </Show>
          </Panel>
        </Suspense>
      </Show>
    </Stack>
  );
}
