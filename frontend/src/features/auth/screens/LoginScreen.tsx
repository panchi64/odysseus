import { createSignal, onCleanup, Show, type JSX } from "solid-js";
import {
  Button,
  Divider,
  Input,
  Row,
  Stack,
  StatusFlag,
  Text,
  Tooltip,
} from "~/ui";
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

  function handleCredentialsSubmit(e: SubmitEvent) {
    e.preventDefault();
    handleSignIn();
  }

  /**
   * Phase 2 behavior: on success, user will be redirected to /app/dashboard.
   * For Phase 1, we show a mock info state to illustrate the flow.
   */
  function handleVerify() {
    if (!totpCode().trim()) {
      setError("Verification code is required.");
      return;
    }
    setError("");
    setLoading(true);
    timers.push(
      setTimeout(() => {
        setLoading(false);
        // Phase 1: backend auth is not wired. In Phase 2, a successful
        // response here would navigate to /app/dashboard.
        setStage("mock-success");
      }, 600),
    );
  }

  function handleVerifySubmit(e: SubmitEvent) {
    e.preventDefault();
    handleVerify();
  }

  return (
    <Stack gap={4}>
      {/* Phase 1 preview banner — shown on all stages */}
      <StatusFlag status="info">
        PHASE 1 PREVIEW — Backend authentication is not wired. This UI is a
        design preview; login will be functional in Phase 2.
      </StatusFlag>

      {/* Stage: Credentials */}
      <Show when={stage() === "credentials"}>
        <form onSubmit={handleCredentialsSubmit}>
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
            <Button variant="primary" type="submit" disabled={loading()}>
              {loading() ? "SIGNING IN…" : "SIGN IN"}
            </Button>
            {/* Account recovery — visible before user is locked in to 2FA */}
            <Row justify="end">
              <Tooltip
                label="Contact your system administrator with your username to reset your password."
                side="top"
              >
                <span class="text-label font-mono text-dim underline cursor-help">
                  FORGOT PASSWORD?
                </span>
              </Tooltip>
            </Row>
          </Stack>
        </form>
      </Show>

      {/* Stage: TOTP */}
      <Show when={stage() === "totp"}>
        <form onSubmit={handleVerifySubmit}>
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
            <Button variant="primary" type="submit" disabled={loading()}>
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
        </form>
      </Show>

      {/* Stage: Mock success (Phase 1 illustration of what Phase 2 will do) */}
      <Show when={stage() === "mock-success"}>
        <Stack gap={3}>
          <StatusFlag status="nominal" dot>
            VERIFICATION ACCEPTED
          </StatusFlag>
          <Text variant="micro" tone="dim">
            In Phase 2, you would now be redirected to the dashboard. Backend
            auth is not yet wired.
          </Text>
          <Button
            variant="ghost"
            onClick={() => {
              setStage("credentials");
              setTotpCode("");
              setError("");
            }}
          >
            BACK TO LOGIN
          </Button>
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
