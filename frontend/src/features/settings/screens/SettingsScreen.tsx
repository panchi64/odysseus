import {
  createSignal,
  For,
  onCleanup,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import {
  Button,
  Divider,
  Field,
  Input,
  LoadingText,
  Modal,
  PageHeader,
  Panel,
  Row,
  Select,
  Stack,
  StatusFlag,
  Tabs,
  Text,
  Toggle,
} from "~/ui";
import { usePreferences, useTwoFactorState } from "../data";
import { MODEL_OPTIONS, LANGUAGE_OPTIONS } from "../mocks";
import type { SettingsTab } from "../model";

export function SettingsScreen(): JSX.Element {
  const prefs = usePreferences();
  const twoFactor = useTwoFactorState();

  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => timers.forEach(clearTimeout));

  const [tab, setTab] = createSignal<SettingsTab>("preferences");

  // Preferences state
  const [model, setModel] = createSignal("");
  const [language, setLanguage] = createSignal("");
  const [rememberSearches, setRememberSearches] = createSignal(true);
  const [cacheEnabled, setCacheEnabled] = createSignal(true);
  const [prefsSaved, setPrefsSaved] = createSignal(false);

  // Security / 2FA state
  const [twoFAEnabled, setTwoFAEnabled] = createSignal(false);
  const [showConfirmModal, setShowConfirmModal] = createSignal(false);
  const [confirmPassword, setConfirmPassword] = createSignal("");
  const [codesRegenerated, setCodesRegenerated] = createSignal(false);

  // Account state
  const [displayName, setDisplayName] = createSignal("");
  const [accountSaved, setAccountSaved] = createSignal(false);

  function initPrefs(p: typeof prefs extends () => infer T ? T : never) {
    if (!p) return;
    if (!model()) setModel(p.model);
    if (!language()) setLanguage(p.language);
  }

  function initTwoFactor(
    t: typeof twoFactor extends () => infer T ? T : never,
  ) {
    if (!t) return;
    setTwoFAEnabled(t.enabled);
  }

  function savePrefs() {
    setPrefsSaved(true);
    timers.push(setTimeout(() => setPrefsSaved(false), 2000));
  }

  function saveAccount() {
    setAccountSaved(true);
    timers.push(setTimeout(() => setAccountSaved(false), 2000));
  }

  function confirmToggle2FA() {
    if (!confirmPassword()) return;
    setTwoFAEnabled((v) => !v);
    setConfirmPassword("");
    setShowConfirmModal(false);
  }

  function regenerateCodes() {
    setCodesRegenerated(true);
    timers.push(setTimeout(() => setCodesRegenerated(false), 2000));
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="SETTINGS"
        subtitle="Preferences, security, and account configuration."
        assetId="ODY-CFG-03.0 EDITION 01"
        actions={
          <StatusFlag status="nominal" dot>
            CONFIGURED
          </StatusFlag>
        }
      />

      <Tabs
        items={[
          { value: "preferences", label: "PREFERENCES" },
          { value: "security", label: "SECURITY" },
          { value: "account", label: "ACCOUNT" },
        ]}
        value={tab()}
        onChange={(v) => setTab(v as SettingsTab)}
      />

      <Suspense fallback={<LoadingText />}>
        <Show when={prefs()} keyed>
          {(p) => {
            initPrefs(p);
            return null;
          }}
        </Show>
        <Show when={twoFactor()} keyed>
          {(t) => {
            initTwoFactor(t);
            return null;
          }}
        </Show>
      </Suspense>

      {/* ── PREFERENCES TAB ───────────────────────────────────── */}
      <Show when={tab() === "preferences"}>
        <Stack gap={4}>
          <Panel label="MODEL & INTERFACE">
            <Stack gap={4}>
              <Select
                label="DEFAULT MODEL"
                options={MODEL_OPTIONS}
                value={model()}
                onChange={setModel}
              />
              <Select
                label="LANGUAGE"
                options={LANGUAGE_OPTIONS}
                value={language()}
                onChange={setLanguage}
              />
              <Field
                label="THEME"
                value="Controlled by top-bar toggle (sun/moon icon)."
                orientation="row"
              />
            </Stack>
          </Panel>

          <Panel label="PRIVACY">
            <Stack gap={3}>
              <Row align="center" justify="between">
                <Stack gap={1}>
                  <Text variant="label" tone="default">
                    REMEMBER SEARCHES
                  </Text>
                  <Text variant="micro" tone="dim">
                    Store recent search queries for autocomplete.
                  </Text>
                </Stack>
                <Toggle
                  checked={rememberSearches()}
                  onChange={setRememberSearches}
                />
              </Row>
              <Divider />
              <Row align="center" justify="between">
                <Stack gap={1}>
                  <Text variant="label" tone="default">
                    RESPONSE CACHE
                  </Text>
                  <Text variant="micro" tone="dim">
                    Cache repeated identical prompts to reduce token usage.
                  </Text>
                </Stack>
                <Toggle checked={cacheEnabled()} onChange={setCacheEnabled} />
              </Row>
            </Stack>
          </Panel>

          <Row justify="end" gap={2}>
            <Show when={prefsSaved()}>
              <StatusFlag status="nominal" dot>
                SAVED
              </StatusFlag>
            </Show>
            <Button variant="primary" onClick={savePrefs}>
              SAVE PREFERENCES
            </Button>
          </Row>
        </Stack>
      </Show>

      {/* ── SECURITY TAB ─────────────────────────────────────── */}
      <Show when={tab() === "security"}>
        <Stack gap={4}>
          <Panel
            label="TWO-FACTOR AUTHENTICATION"
            meta={
              <StatusFlag status={twoFAEnabled() ? "nominal" : "idle"} dot>
                {twoFAEnabled() ? "ENABLED" : "DISABLED"}
              </StatusFlag>
            }
          >
            <Stack gap={4}>
              <Show when={!twoFAEnabled()}>
                <Stack gap={3}>
                  <Text variant="body" tone="dim">
                    Scan the QR code with your authenticator app, then enter
                    your password to enable 2FA.
                  </Text>
                  {/* QR placeholder */}
                  <div class="flex items-center gap-6">
                    <div class="flex h-28 w-28 shrink-0 items-center justify-center border border-line bg-raised">
                      <Stack gap={1} class="items-center">
                        <Text variant="micro" tone="dim">
                          QR CODE
                        </Text>
                        <Text variant="micro" tone="dim">
                          PLACEHOLDER
                        </Text>
                      </Stack>
                    </div>
                    <Stack gap={2}>
                      <Text variant="label" tone="dim">
                        MANUAL ENTRY SECRET
                      </Text>
                      <Suspense fallback={<LoadingText />}>
                        <Text
                          variant="readout"
                          tone="bright"
                          class="font-mono tracking-widest"
                        >
                          {twoFactor()?.secret ?? "—"}
                        </Text>
                      </Suspense>
                      <Text variant="micro" tone="dim">
                        If you cannot scan, enter this code in your
                        authenticator app.
                      </Text>
                    </Stack>
                  </div>
                </Stack>
              </Show>

              <Row align="center" justify="between">
                <Text variant="label" tone="default">
                  ENABLE TWO-FACTOR AUTH
                </Text>
                <Toggle
                  checked={twoFAEnabled()}
                  onChange={() => setShowConfirmModal(true)}
                />
              </Row>
            </Stack>
          </Panel>

          <Panel
            label="BACKUP CODES"
            meta={
              <Button
                variant="ghost"
                size="sm"
                leading="refresh"
                onClick={regenerateCodes}
              >
                {codesRegenerated() ? "REGENERATED" : "REGENERATE"}
              </Button>
            }
          >
            <Stack gap={3}>
              <Text variant="micro" tone="dim">
                Each code can be used once if you lose access to your
                authenticator. Store them securely.
              </Text>
              <Suspense fallback={<LoadingText />}>
                <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <For each={twoFactor()?.backupCodes ?? []}>
                    {(code) => (
                      <div class="border border-line bg-raised px-2 py-1.5">
                        <Text variant="readout" tone="bright" class="font-mono">
                          {code}
                        </Text>
                      </div>
                    )}
                  </For>
                </div>
              </Suspense>
            </Stack>
          </Panel>
        </Stack>
      </Show>

      {/* ── ACCOUNT TAB ──────────────────────────────────────── */}
      <Show when={tab() === "account"}>
        <Stack gap={4}>
          <Panel label="PROFILE">
            <Stack gap={4}>
              <Input
                label="DISPLAY NAME"
                value={displayName() || prefs()?.displayName || ""}
                onInput={(e) => setDisplayName(e.currentTarget.value)}
                placeholder="OPERATOR"
              />
              <Suspense fallback={<LoadingText />}>
                <Field label="USER ID" value={`u-001`} orientation="row" />
                <Field label="ROLE" value="ADMINISTRATOR" orientation="row" />
              </Suspense>
            </Stack>
          </Panel>

          <Row justify="end" gap={2}>
            <Show when={accountSaved()}>
              <StatusFlag status="nominal" dot>
                SAVED
              </StatusFlag>
            </Show>
            <Button variant="primary" onClick={saveAccount}>
              SAVE ACCOUNT
            </Button>
          </Row>
        </Stack>
      </Show>

      {/* ── CONFIRM 2FA MODAL ────────────────────────────────── */}
      <Modal
        open={showConfirmModal()}
        onClose={() => {
          setShowConfirmModal(false);
          setConfirmPassword("");
        }}
        title={
          twoFAEnabled() ? "DISABLE TWO-FACTOR AUTH" : "ENABLE TWO-FACTOR AUTH"
        }
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => {
                setShowConfirmModal(false);
                setConfirmPassword("");
              }}
            >
              CANCEL
            </Button>
            <Button
              variant={twoFAEnabled() ? "danger" : "primary"}
              onClick={confirmToggle2FA}
              disabled={!confirmPassword()}
            >
              CONFIRM
            </Button>
          </>
        }
      >
        <Stack gap={3}>
          <Text variant="body" tone="dim">
            {twoFAEnabled()
              ? "Enter your password to disable two-factor authentication. This will reduce your account security."
              : "Enter your password to confirm enabling two-factor authentication."}
          </Text>
          <Input
            label="CURRENT PASSWORD"
            type="password"
            value={confirmPassword()}
            onInput={(e) => setConfirmPassword(e.currentTarget.value)}
            placeholder="••••••••"
          />
        </Stack>
      </Modal>
    </Stack>
  );
}
