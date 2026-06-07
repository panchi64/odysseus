import {
  createSignal,
  For,
  onCleanup,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import { createStore, produce } from "solid-js/store";
import {
  Button,
  Checkbox,
  confirm,
  Input,
  ListRow,
  LoadingText,
  Menu,
  Modal,
  PageHeader,
  Panel,
  Row,
  Select,
  Stack,
  StatusFlag,
  Text,
  Tooltip,
  toast,
} from "~/ui";
import { timestamp, relativeTime } from "~/lib/format";
import { useTokens } from "../data";
import type { ApiToken, TokenScope, ExpiryOption } from "../model";
import {
  ALL_SCOPES,
  EXPIRY_OPTIONS,
  computeExpiresAt,
  daysUntilExpiry,
} from "../model";

export function ApiTokensScreen(): JSX.Element {
  const tokensResource = useTokens();

  const [tokens, setTokens] = createStore<ApiToken[]>([]);
  let seeded = false;

  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => timers.forEach(clearTimeout));

  // Issue token modal
  const [issueOpen, setIssueOpen] = createSignal(false);
  const [newLabel, setNewLabel] = createSignal("");
  const [newScopes, setNewScopes] = createSignal<TokenScope[]>([]);
  const [newExpiry, setNewExpiry] = createSignal<ExpiryOption>("90d");
  const [issueError, setIssueError] = createSignal<string | null>(null);
  const [issuing, setIssuing] = createSignal(false);

  // Reveal panel: shown once after issue
  const [revealedToken, setRevealedToken] = createSignal<string | null>(null);
  const [copied, setCopied] = createSignal(false);

  function seed(list: ApiToken[]) {
    if (!seeded) {
      seeded = true;
      setTokens(list.map((t) => ({ ...t })));
    }
  }

  function toggleScope(scope: TokenScope) {
    setNewScopes((s) =>
      s.includes(scope) ? s.filter((x) => x !== scope) : [...s, scope],
    );
  }

  function closeIssueModal() {
    setIssueOpen(false);
    setNewLabel("");
    setNewScopes([]);
    setNewExpiry("90d");
    setIssueError(null);
    setIssuing(false);
  }

  async function issueToken() {
    const label = newLabel().trim();
    if (!label || newScopes().length === 0) return;
    setIssueError(null);
    setIssuing(true);
    try {
      // Phase 1: mock async operation — simulates a real API call
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
      const id = `tok-${String(tokens.length + 1).padStart(3, "0")}`;
      const mockSecret = `ody_${Math.random().toString(36).slice(2, 6)}${Math.random().toString(36).slice(2, 10).toUpperCase()}`;
      const token: ApiToken = {
        id,
        label,
        prefix: `${mockSecret.slice(0, 8)}…`,
        scopes: newScopes(),
        createdAt: new Date().toISOString(),
        expiresAt: computeExpiresAt(newExpiry()),
        revoked: false,
      };
      setTokens((t) => [token, ...t]);
      setRevealedToken(mockSecret);
      closeIssueModal();
      toast.success(`Token "${label}" issued — copy it now.`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setIssueError(`Failed to issue token: ${msg}. Please try again.`);
    } finally {
      setIssuing(false);
    }
  }

  async function revokeToken(token: ApiToken) {
    try {
      // Phase 1: mock async operation
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
      setTokens(
        (t) => t.id === token.id,
        produce((t) => {
          t.revoked = true;
        }),
      );
      toast.success(`Token "${token.label}" revoked.`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      toast.error(`Failed to revoke token: ${msg}. Please try again.`);
    }
  }

  async function handleRevokeRequest(token: ApiToken) {
    const ok = await confirm({
      title: `Revoke "${token.label}"?`,
      detail:
        "ALL REQUESTS USING THIS TOKEN WILL IMMEDIATELY FAIL. This cannot be undone.",
      confirmLabel: "REVOKE",
      tone: "alert",
    });
    if (!ok) return;
    await revokeToken(token);
  }

  function copyToken() {
    const tok = revealedToken();
    if (tok) {
      void navigator.clipboard.writeText(tok);
      setCopied(true);
      timers.push(setTimeout(() => setCopied(false), 2000));
    }
  }

  const activeCount = () => tokens.filter((t) => !t.revoked).length;

  /** Render expiry information for a token row. */
  function ExpiryCell(props: { token: ApiToken }): JSX.Element {
    const days = daysUntilExpiry(props.token);
    if (days === null) {
      return (
        <Text variant="micro" tone="dim">
          NO EXPIRY
        </Text>
      );
    }
    if (days <= 0) {
      return (
        <StatusFlag status="alert" dot>
          EXPIRED
        </StatusFlag>
      );
    }
    if (days <= 7) {
      return (
        <Tooltip label={`Expires ${timestamp(props.token.expiresAt!)}`}>
          <StatusFlag status="warn" dot>
            {`EXPIRES IN ${days}D`}
          </StatusFlag>
        </Tooltip>
      );
    }
    return (
      <Tooltip label={`Expires ${timestamp(props.token.expiresAt!)}`}>
        <Text variant="micro" tone="dim">
          {days}D LEFT
        </Text>
      </Tooltip>
    );
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="API TOKENS"
        subtitle="Manage programmatic access keys for the Odysseus API."
        assetId="ODY-ADM-04.0 EDITION 01"
        actions={
          <Row gap={2} align="center">
            <Text variant="micro" tone="dim">
              {activeCount()} ACTIVE
            </Text>
            <Button
              variant="primary"
              leading="plus"
              onClick={() => setIssueOpen(true)}
            >
              ISSUE TOKEN
            </Button>
          </Row>
        }
      />

      <Suspense fallback={<LoadingText />}>
        <Show when={tokensResource()} keyed>
          {(list) => {
            seed(list);
            return null;
          }}
        </Show>
      </Suspense>

      {/* ── REVEALED TOKEN (shown once) ───────────────────────── */}
      <Show when={revealedToken()}>
        <Panel label="NEW TOKEN — SHOWN ONCE" state="active">
          <Stack gap={3}>
            <Row gap={2} align="center">
              <StatusFlag status="warn" dot>
                COPY NOW — NOT SHOWN AGAIN
              </StatusFlag>
            </Row>
            <div class="flex items-center gap-2 border border-line bg-raised px-3 py-2">
              <Text
                variant="readout"
                tone="bright"
                class="flex-1 font-mono break-all"
              >
                {revealedToken()}
              </Text>
              <Button
                variant="ghost"
                size="sm"
                leading={copied() ? "check" : "file"}
                onClick={copyToken}
              >
                {copied() ? "COPIED" : "COPY"}
              </Button>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setRevealedToken(null)}
            >
              DISMISS
            </Button>
          </Stack>
        </Panel>
      </Show>

      <Panel
        label="ISSUED TOKENS"
        meta={
          <Text variant="micro" tone="dim">
            {tokens.length} TOTAL
          </Text>
        }
        flush
      >
        <For each={tokens}>
          {(token, i) => (
            <ListRow
              label={token.label}
              leading="key"
              flush={i() === tokens.length - 1}
              right={
                <Row gap={2} align="center">
                  <Text variant="micro" tone="dim" class="font-mono">
                    {token.prefix}
                  </Text>
                  <Tooltip label={`Scopes: ${token.scopes.join(", ")}`}>
                    <Text variant="micro" tone="dim">
                      {token.scopes.length} SCOPE
                      {token.scopes.length !== 1 ? "S" : ""}
                    </Text>
                  </Tooltip>
                  <Show when={!token.revoked}>
                    <ExpiryCell token={token} />
                  </Show>
                  <Text variant="micro" tone="dim">
                    {token.lastUsedAt
                      ? relativeTime(token.lastUsedAt)
                      : "NEVER USED"}
                  </Text>
                  <StatusFlag status={token.revoked ? "alert" : "nominal"} dot>
                    {token.revoked ? "REVOKED" : "ACTIVE"}
                  </StatusFlag>
                  <Show when={!token.revoked}>
                    <Menu
                      trigger={
                        <Button variant="ghost" size="sm" leading="settings" />
                      }
                      items={[
                        {
                          label: "REVOKE TOKEN",
                          icon: "close",
                          danger: true,
                          onSelect: () => void handleRevokeRequest(token),
                        },
                      ]}
                    />
                  </Show>
                </Row>
              }
            />
          )}
        </For>
        <Show when={tokens.length === 0}>
          <div class="p-4">
            <Text variant="body" tone="dim">
              No tokens issued.
            </Text>
          </div>
        </Show>
      </Panel>

      {/* ── ISSUE TOKEN MODAL ────────────────────────────────── */}
      <Modal
        open={issueOpen()}
        onClose={closeIssueModal}
        title="ISSUE API TOKEN"
        footer={
          <>
            <Button variant="ghost" onClick={closeIssueModal}>
              CANCEL
            </Button>
            <Button
              variant="primary"
              onClick={() => void issueToken()}
              disabled={
                !newLabel().trim() || newScopes().length === 0 || issuing()
              }
            >
              ISSUE
            </Button>
          </>
        }
      >
        <Stack gap={4}>
          {/* Inline error if issuance fails */}
          <Show when={issueError()}>
            <div class="border border-alert bg-surface px-3 py-2">
              <Text variant="body" tone="alert">
                {issueError()}
              </Text>
            </div>
          </Show>

          <Input
            label="TOKEN LABEL"
            value={newLabel()}
            onInput={(e) => setNewLabel(e.currentTarget.value)}
            placeholder="My Automation Script"
          />

          <Stack gap={2}>
            <Text variant="label" tone="dim">
              SCOPES
            </Text>
            <For each={ALL_SCOPES}>
              {(scope) => (
                <Checkbox
                  label={scope.toUpperCase()}
                  checked={newScopes().includes(scope)}
                  onChange={() => toggleScope(scope)}
                />
              )}
            </For>
          </Stack>

          <Select
            label="EXPIRES AFTER"
            options={EXPIRY_OPTIONS}
            value={newExpiry()}
            onChange={(v) => setNewExpiry(v as ExpiryOption)}
          />

          {/* Scope summary — read-only review before issuing */}
          <Show when={newScopes().length > 0}>
            <Stack gap={1}>
              <Text variant="label" tone="dim">
                SELECTED SCOPES
              </Text>
              <Row gap={1} wrap>
                <For each={newScopes()}>
                  {(scope) => (
                    <StatusFlag status="info">{scope.toUpperCase()}</StatusFlag>
                  )}
                </For>
              </Row>
            </Stack>
          </Show>

          <Text variant="micro" tone="dim">
            The full token value will be displayed once after issuance. Store it
            securely.
          </Text>
        </Stack>
      </Modal>
    </Stack>
  );
}
