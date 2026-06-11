import { createSignal, Show, type JSX } from "solid-js";
import { Navigate, useNavigate } from "@solidjs/router";
import { isApiError } from "~/lib/api";
import { useSession } from "~/lib/stores/session";
import { Button, Input, Stack, StatusFlag, Text } from "~/ui";

/**
 * Unlock the workspace. The vault key is password-derived and memory-only, so
 * "sign in" is really "unlock" — one password, no username, no 2FA.
 */
export function LoginScreen(): JSX.Element {
  const session = useSession();
  const navigate = useNavigate();

  const [password, setPassword] = createSignal("");
  const [error, setError] = createSignal("");
  const [loading, setLoading] = createSignal(false);

  async function handleUnlock(e: SubmitEvent) {
    e.preventDefault();
    if (!password().trim()) {
      setError("Password is required.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      await session.unlock(password());
      navigate("/", { replace: true });
    } catch (err) {
      setError(
        isApiError(err) && err.status === 401
          ? "Incorrect password."
          : "Unable to unlock. Check the backend connection.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      {/* Already unlocked (e.g. opened /login directly) → straight to the app.
          First-run with no operator set → the setup screen. */}
      <Show when={session.status === "unlocked"}>
        <Navigate href="/" />
      </Show>
      <Show when={session.status === "uninitialized"}>
        <Navigate href="/signup" />
      </Show>

      <form onSubmit={handleUnlock}>
        <Stack gap={3}>
          <Stack gap={1}>
            <StatusFlag status="idle" dot>
              WORKSPACE LOCKED
            </StatusFlag>
            <Text variant="micro" tone="dim">
              Enter the operator password to unlock encrypted storage.
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
            autocomplete="current-password"
          />
          <Show when={error()}>
            <Text variant="micro" tone="alert">
              {error()}
            </Text>
          </Show>
          <Button variant="primary" type="submit" disabled={loading()}>
            {loading() ? "UNLOCKING…" : "UNLOCK"}
          </Button>
        </Stack>
      </form>
    </>
  );
}
