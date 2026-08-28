import { Show, createSignal, type JSX } from "solid-js";
import {
  Button,
  Icon,
  Input,
  PageHeader,
  Panel,
  Readout,
  Stack,
  StatusFlag,
  Text,
  toast,
  type Status,
} from "~/ui";
import { isApiError } from "~/lib/api";
import { requestHostMode } from "../data";
import type { HostModeGrant, SessionEnd, SessionPhase } from "../model";
import { Terminal } from "../components/Terminal";

/** Chip label + accent for the current session phase. */
function flagFor(phase: SessionPhase): { status: Status; label: string } {
  switch (phase) {
    case "authenticating":
      return { status: "info", label: "AUTHENTICATING" };
    case "connecting":
      return { status: "warn", label: "CONNECTING" };
    case "live":
      return { status: "warn", label: "SESSION LIVE" };
    case "ended":
      return { status: "idle", label: "SESSION ENDED" };
    case "denied":
      return { status: "alert", label: "ACCESS DENIED" };
    default:
      return { status: "idle", label: "HOST MODE" };
  }
}

export function ShellScreen(): JSX.Element {
  const [phase, setPhase] = createSignal<SessionPhase>("prompt");
  const [password, setPassword] = createSignal("");
  const [error, setError] = createSignal("");
  const [grant, setGrant] = createSignal<HostModeGrant>();
  const [end, setEnd] = createSignal<SessionEnd>();

  async function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    const pw = password();
    if (!pw) {
      setError("Password is required.");
      return;
    }
    setError("");
    setPhase("authenticating");
    try {
      const g = await requestHostMode(pw);
      setPassword("");
      setEnd(undefined);
      setGrant(g);
      setPhase("connecting");
    } catch (err) {
      setPhase("denied");
      if (isApiError(err) && err.status === 401) {
        setError("Invalid password.");
      } else if (isApiError(err) && err.status === 429) {
        setError(`Rate limited — ${err.detail || "try again shortly"}.`);
      } else if (isApiError(err)) {
        setError(err.detail || "Unable to grant host mode.");
      } else {
        setError("Unable to reach the backend.");
      }
    }
  }

  /** Drop the terminal and return to the HOST MODE prompt — a fresh
   *  challenge is minted every session by design. */
  function reconnect() {
    setGrant(undefined);
    setEnd(undefined);
    setError("");
    setPhase("prompt");
  }

  function handleEnded(sessionEnd: SessionEnd) {
    setEnd(sessionEnd);
    setPhase("ended");
  }

  function handleAuthFailure() {
    // handleAuthFailure() (~/lib/api) already cleared the session token and
    // routed to login via the session store — nothing further to do here.
  }

  function handleExpired() {
    toast.warn("Host mode expired — re-authenticate.");
    setGrant(undefined);
    setPhase("prompt");
  }

  const flag = () => flagFor(phase());
  const showPrompt = () =>
    phase() === "prompt" ||
    phase() === "authenticating" ||
    phase() === "denied";
  const showTerminal = () => phase() === "connecting" || phase() === "live";

  return (
    <Stack gap={6} class="flex h-full min-h-0 flex-col">
      <PageHeader
        title="OPERATOR SHELL"
        subtitle="Live terminal on the server host. Re-authentication required every session."
        assetId="ODY-ADM-07.0 EDITION 02"
        actions={
          <StatusFlag status={flag().status} dot pulse={phase() === "live"}>
            {flag().label}
          </StatusFlag>
        }
      />

      <Show when={showPrompt()}>
        <Panel label="HOST MODE" class="max-w-md">
          <Stack gap={4}>
            <div class="flex items-center gap-2 border border-alert px-3 py-2">
              <Icon name="warning" size={12} class="text-alert shrink-0" />
              <Text variant="micro" tone="alert">
                Grants a live shell on the server host with server-process
                privileges. Administrator only. No undo.
              </Text>
            </div>
            <form onSubmit={(e) => void handleSubmit(e)}>
              <Stack gap={3}>
                <Input
                  label="OPERATOR PASSWORD"
                  type="password"
                  value={password()}
                  onInput={(e) => {
                    setPassword(e.currentTarget.value);
                    setError("");
                  }}
                  placeholder="••••••••"
                  autocomplete="current-password"
                  disabled={phase() === "authenticating"}
                  invalid={!!error()}
                  hint={error() || undefined}
                />
                <Button
                  variant="primary"
                  type="submit"
                  disabled={phase() === "authenticating" || !password()}
                >
                  {phase() === "authenticating"
                    ? "AUTHENTICATING…"
                    : "ENTER HOST MODE"}
                </Button>
              </Stack>
            </form>
          </Stack>
        </Panel>
      </Show>

      <Show when={showTerminal() && grant()}>
        {(g) => (
          <Panel label="TERMINAL" flush fill class="h-full">
            <div class="flex h-full min-h-0 flex-col">
              <Terminal
                token={g().token}
                onReady={() => setPhase("live")}
                onEnded={handleEnded}
                onAuthFailure={handleAuthFailure}
                onExpired={handleExpired}
              />
            </div>
          </Panel>
        )}
      </Show>

      <Show when={phase() === "ended"}>
        <Panel label="SESSION ENDED" class="max-w-md">
          <Stack gap={4}>
            <Readout
              label="EXIT CODE"
              value={end()?.exitCode ?? "—"}
              tone={end()?.exitCode === 0 ? "nominal" : "alert"}
            />
            <Text variant="micro" tone="dim">
              {end()?.reason}
            </Text>
            <Button variant="primary" leading="refresh" onClick={reconnect}>
              RECONNECT
            </Button>
          </Stack>
        </Panel>
      </Show>
    </Stack>
  );
}
