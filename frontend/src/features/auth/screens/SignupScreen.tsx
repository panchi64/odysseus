import { createSignal, Show, type JSX } from "solid-js";
import { Navigate } from "@solidjs/router";
import { isApiError } from "~/lib/api";
import { useSession } from "~/lib/stores/session";
import { Button, Input, Stack, StatusFlag, Text } from "~/ui";

/**
 * First-run setup: choose the operator password. This derives the vault key and
 * unlocks the workspace — there is exactly one operator, so this runs once. After
 * setup, this surface redirects to login (the workspace is already initialized).
 */
export function SignupScreen(): JSX.Element {
  const session = useSession();

  const [password, setPassword] = createSignal("");
  const [confirm, setConfirm] = createSignal("");
  const [error, setError] = createSignal("");
  const [loading, setLoading] = createSignal(false);

  const mismatch = () => confirm().length > 0 && password() !== confirm();

  async function handleCreate(e: SubmitEvent) {
    e.preventDefault();
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
    try {
      // Setup flips the session to "unlocked"; the reactive <Navigate> below
      // redirects home. A second imperative navigate would race that route
      // transition and blank the page.
      await session.setup(password());
    } catch (err) {
      setError(
        isApiError(err) && err.status === 409
          ? "The workspace is already initialized."
          : "Unable to complete setup. Check the backend connection.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      {/* Already set up → don't offer setup again. */}
      <Show when={session.status === "unlocked"}>
        <Navigate href="/" />
      </Show>
      <Show when={session.status === "locked"}>
        <Navigate href="/login" />
      </Show>

      <form onSubmit={handleCreate}>
        <Stack gap={3}>
          <Stack gap={1}>
            <StatusFlag status="info" dot>
              FIRST-RUN SETUP
            </StatusFlag>
            <Text variant="micro" tone="dim">
              Choose the operator password. It derives the encryption key for
              all stored data and is never recoverable — store it safely.
            </Text>
          </Stack>
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
            invalid={mismatch()}
            hint={mismatch() ? "Passwords do not match." : undefined}
            autocomplete="new-password"
          />
          <Show when={error()}>
            <Text variant="micro" tone="alert">
              {error()}
            </Text>
          </Show>
          <Button
            variant="primary"
            type="submit"
            disabled={loading() || mismatch()}
          >
            {loading() ? "INITIALIZING…" : "INITIALIZE WORKSPACE"}
          </Button>
        </Stack>
      </form>
    </>
  );
}
