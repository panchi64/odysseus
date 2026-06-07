import { createSignal, onCleanup, Show, type JSX } from "solid-js";
import { Button, Divider, Input, Row, Stack, Text } from "~/ui";

export function SignupScreen(): JSX.Element {
  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => timers.forEach(clearTimeout));

  const [username, setUsername] = createSignal("");
  const [password, setPassword] = createSignal("");
  const [confirm, setConfirm] = createSignal("");
  const [error, setError] = createSignal("");
  const [loading, setLoading] = createSignal(false);

  const passwordMismatch = () =>
    confirm().length > 0 && password() !== confirm();

  function handleCreate() {
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
    timers.push(
      setTimeout(() => {
        setLoading(false);
        setError("MOCK: Registration not wired yet — Phase 1 UI only.");
      }, 600),
    );
  }

  return (
    <Stack gap={4}>
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
        <Show when={error()}>
          <Text variant="micro" tone="alert">
            {error()}
          </Text>
        </Show>
        <Button
          variant="primary"
          onClick={handleCreate}
          disabled={loading() || passwordMismatch()}
        >
          {loading() ? "CREATING…" : "CREATE ACCOUNT"}
        </Button>
        <Text variant="micro" tone="dim">
          Account creation is rate-limited. Admins may disable
          self-registration.
        </Text>
      </Stack>

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
  );
}
