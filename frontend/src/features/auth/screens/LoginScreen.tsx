import { createSignal, onCleanup, Show, type JSX } from "solid-js";
import { Button, Divider, Input, Row, Stack, StatusFlag, Text } from "~/ui";
import type { LoginStage } from "../model";

export function LoginScreen(): JSX.Element {
  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => timers.forEach(clearTimeout));

  const [stage, setStage] = createSignal<LoginStage>("credentials");
  const [username, setUsername] = createSignal("");
  const [password, setPassword] = createSignal("");
  const [totpCode, setTotpCode] = createSignal("");
  const [backupMode, setBackupMode] = createSignal(false);
  const [error, setError] = createSignal("");
  const [loading, setLoading] = createSignal(false);

  function handleSignIn() {
    if (!username().trim() || !password().trim()) {
      setError("Username and password are required.");
      return;
    }
    setError("");
    setLoading(true);
    // Mock: advance to 2FA stage after brief delay
    timers.push(
      setTimeout(() => {
        setLoading(false);
        setStage("totp");
      }, 600),
    );
  }

  function handleVerify() {
    if (!totpCode().trim()) {
      setError("Verification code is required.");
      return;
    }
    setError("");
    setLoading(true);
    // Mock: stay on page (no real auth)
    timers.push(
      setTimeout(() => {
        setLoading(false);
        setError("MOCK: Auth not wired yet — this is Phase 1 UI only.");
      }, 600),
    );
  }

  return (
    <Stack gap={4}>
      {/* Stage: Credentials */}
      <Show when={stage() === "credentials"}>
        <Stack gap={3}>
          <Input
            label="USERNAME"
            value={username()}
            onInput={(e) => {
              setUsername(e.currentTarget.value);
              setError("");
            }}
            placeholder="operator"
            autocomplete="username"
          />
          <Input
            label="PASSWORD"
            type="password"
            value={password()}
            onInput={(e) => {
              setPassword(e.currentTarget.value);
              setError("");
            }}
            placeholder="••••••••"
            autocomplete="current-password"
          />
          <Show when={error()}>
            <Text variant="micro" tone="alert">
              {error()}
            </Text>
          </Show>
          <Button
            variant="primary"
            type="submit"
            onClick={handleSignIn}
            disabled={loading()}
          >
            {loading() ? "SIGNING IN…" : "SIGN IN"}
          </Button>
        </Stack>
      </Show>

      {/* Stage: TOTP */}
      <Show when={stage() === "totp"}>
        <Stack gap={3}>
          <Stack gap={1}>
            <StatusFlag status="info" dot>
              TWO-FACTOR REQUIRED
            </StatusFlag>
            <Text variant="micro" tone="dim">
              {backupMode()
                ? "Enter one of your 8-character backup codes."
                : "Enter the 6-digit code from your authenticator app."}
            </Text>
          </Stack>
          <Input
            label={backupMode() ? "BACKUP CODE" : "TOTP CODE"}
            value={totpCode()}
            onInput={(e) => {
              setTotpCode(e.currentTarget.value);
              setError("");
            }}
            placeholder={backupMode() ? "XXXX-XXXX" : "000000"}
            autocomplete="one-time-code"
          />
          <Show when={error()}>
            <Text variant="micro" tone="alert">
              {error()}
            </Text>
          </Show>
          <Button variant="primary" onClick={handleVerify} disabled={loading()}>
            {loading() ? "VERIFYING…" : "VERIFY"}
          </Button>
          <Row justify="between" align="center">
            <button
              type="button"
              class="text-label font-mono text-dim underline hover:text-bright transition-colors"
              onClick={() => {
                setBackupMode((v) => !v);
                setTotpCode("");
                setError("");
              }}
            >
              {backupMode() ? "USE AUTHENTICATOR APP" : "USE BACKUP CODE"}
            </button>
            <button
              type="button"
              class="text-label font-mono text-dim underline hover:text-bright transition-colors"
              onClick={() => {
                setStage("credentials");
                setTotpCode("");
                setError("");
              }}
            >
              BACK
            </button>
          </Row>
        </Stack>
      </Show>

      <Divider />

      <Row gap={2} align="center" justify="between">
        <Text variant="micro" tone="dim">
          Access is rate-limited.
        </Text>
        <a
          href="/signup"
          class="text-label font-mono text-dim underline hover:text-bright transition-colors"
        >
          CREATE ACCOUNT →
        </a>
      </Row>
    </Stack>
  );
}
