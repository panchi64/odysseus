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
  Tooltip,
} from "~/ui";
import { timestamp, relativeTime } from "~/lib/format";
import { useTokens } from "../data";
import type { ApiToken, TokenScope } from "../model";
import { ALL_SCOPES } from "../model";

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

  // Reveal panel: shown once after issue
  const [revealedToken, setRevealedToken] = createSignal<string | null>(null);
  const [copied, setCopied] = createSignal(false);

  // Revoke confirm
  const [revokeTarget, setRevokeTarget] = createSignal<ApiToken | null>(null);

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

  function issueToken() {
    if (!newLabel().trim() || newScopes().length === 0) return;
    const id = `tok-${String(tokens.length + 1).padStart(3, "0")}`;
    const mockSecret = `ody_${Math.random().toString(36).slice(2, 6)}${Math.random().toString(36).slice(2, 10).toUpperCase()}`;
    const token: ApiToken = {
      id,
      label: newLabel(),
      prefix: `${mockSecret.slice(0, 8)}…`,
      scopes: newScopes(),
      createdAt: new Date().toISOString(),
      revoked: false,
    };
    setTokens((t) => [token, ...t]);
    setRevealedToken(mockSecret);
    setNewLabel("");
    setNewScopes([]);
    setIssueOpen(false);
  }

  function revokeToken(id: string) {
    setTokens(
      (t) => t.id === id,
      produce((t) => {
        t.revoked = true;
      }),
    );
    setRevokeTarget(null);
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
                          onSelect: () => setRevokeTarget(token),
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
        onClose={() => {
          setIssueOpen(false);
          setNewLabel("");
          setNewScopes([]);
        }}
        title="ISSUE API TOKEN"
        footer={
          <>
            <Button variant="ghost" onClick={() => setIssueOpen(false)}>
              CANCEL
            </Button>
            <Button
              variant="primary"
              onClick={issueToken}
              disabled={!newLabel().trim() || newScopes().length === 0}
            >
              ISSUE
            </Button>
          </>
        }
      >
        <Stack gap={4}>
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
          <Text variant="micro" tone="dim">
            The full token value will be displayed once after issuance. Store it
            securely.
          </Text>
        </Stack>
      </Modal>

      {/* ── REVOKE CONFIRM MODAL ─────────────────────────────── */}
      <Modal
        open={revokeTarget() !== null}
        onClose={() => setRevokeTarget(null)}
        title="REVOKE TOKEN"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRevokeTarget(null)}>
              CANCEL
            </Button>
            <Button
              variant="danger"
              onClick={() => revokeTarget() && revokeToken(revokeTarget()!.id)}
            >
              REVOKE
            </Button>
          </>
        }
      >
        <Stack gap={2}>
          <Text variant="body" tone="default">
            Revoke{" "}
            <Text as="span" tone="bright">
              {revokeTarget()?.label}
            </Text>
            ?
          </Text>
          <Text variant="micro" tone="dim">
            Created{" "}
            {revokeTarget() ? timestamp(revokeTarget()!.createdAt) : "—"}. All
            requests using this token will immediately fail.
          </Text>
        </Stack>
      </Modal>
    </Stack>
  );
}
