import { createSignal, onCleanup, Show, type JSX } from "solid-js";
import { Button, Divider, Input, Row, Stack, StatusFlag, Text } from "~/ui";

export function SignupScreen(): JSX.Element {
  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => timers.forEach(clearTimeout));

  const [username, setUsername] = createSignal("");
  const [password, setPassword] = createSignal("");
  const [confirm, setConfirm] = createSignal("");
  const [error, setError] = createSignal("");
  const [loading, setLoading] = createSignal(false);
  const [created, setCreated] = createSignal(false);

  const passwordMismatch = () =>
    confirm().length > 0 && password() !== confirm();

  function handleCreate(e?: SubmitEvent) {
    e?.preventDefault();
    if (!username().trim()) {
      setError("Username is required.");
      return;
    }
    if (password().length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password() !== confirm()) {
      setError("Passwords do not match.");
      return;
    }
    setError("");
    setLoading(true);
    // Phase 1 mock: simulate success and show next-steps guidance.
    // Phase 2: POST /api/auth/register — on 201, navigate to /login with
    // a flash message "Account created — sign in with your credentials."
    timers.push(
      setTimeout(() => {
        setLoading(false);
        setCreated(true);
      }, 600),
    );
  }

  // Success state — shown after mock account creation
  return (
    <Show
      when={!created()}
      fallback={
        <Stack gap={4}>
          <StatusFlag status="nominal" dot>
            ACCOUNT CREATED
          </StatusFlag>
          <Text variant="micro" tone="dim">
            Your account has been created. Sign in with your credentials to
            access the workspace.
          </Text>
          <a href="/login">
            <Button variant="primary" type="button">
              SIGN IN →
            </Button>
          </a>
        </Stack>
      }
    >
      <Stack gap={4}>
        {/* Top navigation — visible exit before the form */}
        <Row justify="start">
          <a
            href="/login"
            class="text-label font-mono text-dim underline hover:text-bright transition-colors"
          >
            ← BACK TO SIGN IN
          </a>
        </Row>

        <form onSubmit={handleCreate}>
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
              hint="Minimum 8 characters."
              autocomplete="new-password"
            />
            <Input
              label="CONFIRM PASSWORD"
              type="password"
              value={confirm()}
              onInput={(e) => {
                setConfirm(e.currentTarget.value);
                setError("");
              }}
              placeholder="••••••••"
              invalid={passwordMismatch()}
              hint={passwordMismatch() ? "Passwords do not match." : undefined}
              autocomplete="new-password"
            />
            {/* Mismatch warning echoed above the button for clarity */}
            <Show when={passwordMismatch()}>
              <StatusFlag status="warn">
                Passwords do not match — resolve before submitting.
              </StatusFlag>
            </Show>
            <Show when={error()}>
              <Text variant="micro" tone="alert">
                {error()}
              </Text>
            </Show>
            <Button
              variant="primary"
              type="submit"
              disabled={loading() || passwordMismatch()}
            >
              {loading() ? "CREATING…" : "CREATE ACCOUNT"}
            </Button>
            <Text variant="micro" tone="dim">
              Account creation is rate-limited. Admins may disable
              self-registration.
            </Text>
          </Stack>
        </form>

        <Divider />

        <Row justify="end">
          <a
            href="/login"
            class="text-label font-mono text-dim underline hover:text-bright transition-colors"
          >
            ← SIGN IN
          </a>
        </Row>
      </Stack>
    </Show>
  );
}
