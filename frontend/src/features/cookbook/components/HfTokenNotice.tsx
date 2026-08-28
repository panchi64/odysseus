import { createSignal, Show, type JSX } from "solid-js";
import { Button, ExternalLink, Input, Row, Stack, Text, toast } from "~/ui";
import { setCredential, useCredentials } from "~/features/tokens/data";

const HF_SERVICE = "huggingface";
const HF_TOKENS_URL = "https://huggingface.co/settings/tokens";

/** Optional inline step to add a Hugging Face token from the local-serve flow. A token is
 *  NOT required — public models download without one; it only speeds downloads and unlocks
 *  gated/private repos. Hidden once a token is stored (manage it on the API Tokens page).
 *
 *  Presentation-only: the token is sent once to the credential store and sealed
 *  server-side; it is never read back. The store is the single source of truth for whether
 *  one is set, shared with the API Tokens surface. */
export function HfTokenNotice(): JSX.Element {
  const credentials = useCredentials();
  const hasToken = () =>
    (credentials() ?? []).some((c) => c.service === HF_SERVICE && c.hasKey);

  const [open, setOpen] = createSignal(false);
  const [token, setToken] = createSignal("");
  const [saving, setSaving] = createSignal(false);

  const close = () => {
    setOpen(false);
    setToken("");
  };

  async function save(): Promise<void> {
    if (!token().trim() || saving()) return;
    setSaving(true);
    try {
      await setCredential(HF_SERVICE, token().trim());
      toast.success("Hugging Face token saved");
      close();
    } catch (err) {
      toast.error(
        (err as { detail?: string })?.detail ?? "Couldn't save the token",
      );
    } finally {
      setSaving(false);
    }
  }

  // Only surface this while a token is genuinely absent (and the status has loaded).
  return (
    <Show when={credentials() && !hasToken()}>
      <div class="rounded-panel bg-surface p-3 shadow-1">
        <Show
          when={open()}
          fallback={
            <Row align="center" justify="between" gap={3}>
              <Text variant="micro" tone="dim">
                Optional: add a Hugging Face token for faster downloads and
                access to gated repos. Public models download without one.
              </Text>
              <Button
                variant="ghost"
                size="sm"
                leading="key"
                onClick={() => setOpen(true)}
              >
                Add token
              </Button>
            </Row>
          }
        >
          <Stack gap={2}>
            <Text variant="micro" tone="dim">
              A token isn't required — public models download without one. Add
              yours for faster downloads and to reach gated or private repos.
              Create one on Hugging Face (a read-scoped token is enough), then
              paste it below.
            </Text>
            <ExternalLink href={HF_TOKENS_URL}>
              Create a token on Hugging Face ↗
            </ExternalLink>
            <Row gap={2} align="end" class="flex-wrap">
              <div class="min-w-0 flex-1">
                <Input
                  label="Hugging Face token"
                  type="password"
                  placeholder="hf_…"
                  value={token()}
                  onInput={(e) => setToken(e.currentTarget.value)}
                  hint="Sealed at rest and never shown again after saving."
                />
              </div>
              <Button variant="ghost" disabled={saving()} onClick={close}>
                Cancel
              </Button>
              <Button
                variant="primary"
                leading="key"
                disabled={!token().trim() || saving()}
                onClick={() => void save()}
              >
                {saving() ? "Saving…" : "Save token"}
              </Button>
            </Row>
          </Stack>
        </Show>
      </div>
    </Show>
  );
}
