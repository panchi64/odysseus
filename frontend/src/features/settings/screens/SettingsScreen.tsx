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
  toast,
} from "~/ui";
import { usePreferences, useTwoFactorState } from "../data";
import { MODEL_OPTIONS, LANGUAGE_OPTIONS } from "../mocks";
import type { SettingsTab } from "../model";

const DISPLAY_NAME_MAX = 50;

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
  const [prefsSaving, setPrefsSaving] = createSignal(false);

  // Security / 2FA state
  // twoFAEnabled tracks the committed (saved) state
  const [twoFAEnabled, setTwoFAEnabled] = createSignal(false);
  const [twoFAInitialized, setTwoFAInitialized] = createSignal(false);
  const [showConfirmModal, setShowConfirmModal] = createSignal(false);
  const [confirmPassword, setConfirmPassword] = createSignal("");
  const [disableConfirmText, setDisableConfirmText] = createSignal("");
  const [twoFAPending, setTwoFAPending] = createSignal<
    "enabled" | "disabled" | null
  >(null);
  const [codesRegenerated, setCodesRegenerated] = createSignal(false);

  // Account state
  const [displayName, setDisplayName] = createSignal("");
  const [accountSaved, setAccountSaved] = createSignal(false);

  // Track whether local state has unsaved changes
  function prefsChanged() {
    const p = prefs();
    if (!p) return false;
    return (
      model() !== p.model ||
      language() !== p.language ||
      rememberSearches() !== p.rememberSearches ||
      cacheEnabled() !== p.cacheEnabled
    );
  }

  function accountChanged() {
    const p = prefs();
    if (!p) return false;
    const loaded = p.displayName ?? "";
    const current = displayName() !== "" ? displayName() : loaded;
    return current !== loaded;
  }

  function initPrefs(p: typeof prefs extends () => infer T ? T : never) {
    if (!p) return;
    if (!model()) setModel(p.model);
    if (!language()) setLanguage(p.language);
    setRememberSearches(p.rememberSearches);
    setCacheEnabled(p.cacheEnabled);
  }

  function initTwoFactor(
    t: typeof twoFactor extends () => infer T ? T : never,
  ) {
    if (!t) return;
    if (!twoFAInitialized()) {
      setTwoFAEnabled(t.enabled);
      setTwoFAInitialized(true);
    }
  }

  function resetPrefs() {
    const p = prefs();
    if (!p) return;
    setModel(p.model);
    setLanguage(p.language);
    setRememberSearches(p.rememberSearches);
    setCacheEnabled(p.cacheEnabled);
    toast.info("Changes discarded.");
  }

  function resetAccount() {
    const p = prefs();
    if (!p) return;
    setDisplayName(p.displayName ?? "");
    toast.info("Changes discarded.");
  }

  function savePrefs() {
    setPrefsSaving(true);
    timers.push(
      setTimeout(() => {
        setPrefsSaving(false);
        setPrefsSaved(true);
        toast.success("Preferences saved.");
        timers.push(setTimeout(() => setPrefsSaved(false), 2000));
      }, 600),
    );
  }

  function saveAccount() {
    const name = displayName() || prefs()?.displayName || "";
    if (!name.trim()) {
      toast.error("Display name cannot be empty.");
      return;
    }
    if (name.length > DISPLAY_NAME_MAX) {
      toast.error(
        `Display name must be ${DISPLAY_NAME_MAX} characters or fewer.`,
      );
      return;
    }
    setAccountSaved(true);
    toast.success("Account saved.");
    timers.push(setTimeout(() => setAccountSaved(false), 2000));
  }

  // Open 2FA modal — do NOT flip twoFAEnabled yet. It will only flip on confirm.
  function handleToggle2FA() {
    setConfirmPassword("");
    setDisableConfirmText("");
    setShowConfirmModal(true);
    setTwoFAPending(null);
  }

  // Shared close/cancel for modal — always restores UI to committed state
  function closeModal() {
    setShowConfirmModal(false);
    setConfirmPassword("");
    setDisableConfirmText("");
    setTwoFAPending(null);
  }

  function confirmToggle2FA() {
    if (!confirmPassword()) return;
    const enabling = !twoFAEnabled();
    if (!enabling && disableConfirmText().toUpperCase() !== "DISABLE") return;

    // Commit the toggle
    setTwoFAEnabled(enabling);
    setTwoFAPending(enabling ? "enabled" : "disabled");
    closeModal();

    toast.success(
      enabling ? "Two-factor auth enabled." : "Two-factor auth disabled.",
    );

    timers.push(setTimeout(() => setTwoFAPending(null), 2000));
  }

  function regenerateCodes() {
    setCodesRegenerated(true);
    toast.success("Backup codes regenerated. Store them securely.");
    timers.push(setTimeout(() => setCodesRegenerated(false), 2000));
  }

  // Whether the disable confirmation typed field is satisfied
  function disableConfirmValid() {
    return disableConfirmText().toUpperCase() === "DISABLE";
  }

  const currentDisplayName = () =>
    displayName() !== "" ? displayName() : (prefs()?.displayName ?? "");
  const displayNameLength = () => currentDisplayName().length;

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
                onChange={(v) => {
                  setModel(v);
                  setPrefsSaving(true);
                  timers.push(
                    setTimeout(() => {
                      setPrefsSaving(false);
                      toast.info("Model selection updated — save to persist.");
                    }, 400),
                  );
                }}
                disabled={prefsSaving()}
              />
              <Show when={prefsSaving()}>
                <Text variant="micro" tone="dim">
                  UPDATING…
                </Text>
              </Show>
              <Select
                label="LANGUAGE"
                options={LANGUAGE_OPTIONS}
                value={language()}
                onChange={(v) => {
                  setLanguage(v);
                }}
                disabled={prefsSaving()}
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
            <Show when={prefsChanged() && !prefsSaved()}>
              <StatusFlag status="warn" dot>
                UNSAVED
              </StatusFlag>
            </Show>
            <Show when={prefsChanged()}>
              <Button
                variant="ghost"
                onClick={resetPrefs}
                disabled={prefsSaving()}
              >
                RESET
              </Button>
            </Show>
            <Button
              variant="primary"
              onClick={savePrefs}
              disabled={prefsSaving()}
            >
              {prefsSaving() ? "SAVING…" : "SAVE PREFERENCES"}
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
              <Show
                when={twoFAPending() !== null}
                fallback={
                  <StatusFlag status={twoFAEnabled() ? "nominal" : "idle"} dot>
                    {twoFAEnabled() ? "ENABLED" : "DISABLED"}
                  </StatusFlag>
                }
              >
                <StatusFlag status="nominal" dot>
                  {twoFAPending() === "enabled" ? "ENABLED" : "DISABLED"}
                </StatusFlag>
              </Show>
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
                <Toggle checked={twoFAEnabled()} onChange={handleToggle2FA} />
              </Row>

              <Show when={showConfirmModal()}>
                <StatusFlag status="warn" dot>
                  PENDING — confirm in dialog
                </StatusFlag>
              </Show>
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
              <Stack gap={1}>
                <Input
                  label="DISPLAY NAME"
                  value={currentDisplayName()}
                  onInput={(e) => setDisplayName(e.currentTarget.value)}
                  placeholder="OPERATOR"
                  maxlength={DISPLAY_NAME_MAX}
                  invalid={displayNameLength() > DISPLAY_NAME_MAX}
                  hint={`${displayNameLength()} / ${DISPLAY_NAME_MAX}`}
                />
              </Stack>
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
            <Show when={accountChanged() && !accountSaved()}>
              <StatusFlag status="warn" dot>
                UNSAVED
              </StatusFlag>
            </Show>
            <Show when={accountChanged()}>
              <Button variant="ghost" onClick={resetAccount}>
                RESET
              </Button>
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
        onClose={closeModal}
        title={
          twoFAEnabled() ? "DISABLE TWO-FACTOR AUTH" : "ENABLE TWO-FACTOR AUTH"
        }
        footer={
          <>
            <Button variant="ghost" onClick={closeModal}>
              CANCEL
            </Button>
            <Button
              variant={twoFAEnabled() ? "danger" : "primary"}
              onClick={confirmToggle2FA}
              disabled={
                !confirmPassword() || (twoFAEnabled() && !disableConfirmValid())
              }
            >
              {twoFAEnabled() ? "DISABLE 2FA" : "CONFIRM"}
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
          <Show when={twoFAEnabled()}>
            <Text variant="micro" tone="alert">
              This is a security-critical action. Type DISABLE below to confirm.
            </Text>
            <Input
              label='TYPE "DISABLE" TO CONFIRM'
              value={disableConfirmText()}
              onInput={(e) => setDisableConfirmText(e.currentTarget.value)}
              placeholder="DISABLE"
              invalid={
                disableConfirmText().length > 0 && !disableConfirmValid()
              }
            />
          </Show>
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
