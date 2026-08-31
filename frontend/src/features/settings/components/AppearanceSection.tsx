import { For, Show, type JSX } from "solid-js";
import { SESSION_MODES } from "~/lib/modes";
import {
  ACCENT_TOKENS,
  Button,
  ColorField,
  Divider,
  Panel,
  Row,
  Stack,
  Text,
  ThemeToggle,
  accentOverrides,
  accentValue,
  hasAccentOverrides,
  isAccentOverridden,
  isSessionAccentOverridden,
  resetAccent,
  resetSessionAccent,
  resetAllAccents,
  restoreAccents,
  sessionAccentValue,
  setAccent,
  setSessionAccent,
  toast,
  useTheme,
  type AccentTokenSpec,
  type ThemeMode,
} from "~/ui";

/** Which palette the accent editor is writing. Named in the machine's voice
 *  because it is the *resolved* mode — a fact about the current state, not the
 *  operator's three-way preference. */
const MODE_LABEL: Record<string, string> = {
  phosphor: "Phosphor",
  paper: "Paper",
};

/** The signature accent, once per session mode.
 *
 *  The only row with a second axis, and deliberately so. The other four accents
 *  are a closed set of *meanings* — rebinding "alert" per mode would make red
 *  mean one thing in a code thread and another in a research thread. The
 *  signature's job is to say *where you are*, so the mode is exactly the thing it
 *  should carry, and this is where the operator retunes it.
 *
 *  Normal is offered alongside the other two even though it has no rule of its
 *  own: it writes through to the base `--accent`, which is what moves it. Showing
 *  it keeps the three visible together — the point of retuning one is how it
 *  compares to the others. */
function SignatureRow(props: {
  spec: AccentTokenSpec;
  mode: ThemeMode;
}): JSX.Element {
  return (
    <Stack gap={2}>
      <Stack gap={1}>
        <Text variant="label" tone="default">
          {props.spec.label}
        </Text>
        <Text variant="micro" tone="dim">
          {props.spec.description} One per session mode — it is how the window
          says which kind of thread is open.
        </Text>
      </Stack>
      <Stack gap={3} class="pl-3">
        <For each={SESSION_MODES}>
          {(session) => (
            <ColorField
              label={session.label}
              mode={props.mode}
              value={sessionAccentValue(props.mode, session.id)}
              onInput={(hex) =>
                setSessionAccent(props.mode, session.id, hex, {
                  persist: false,
                })
              }
              onChange={(hex) => setSessionAccent(props.mode, session.id, hex)}
              onReset={
                isSessionAccentOverridden(props.mode, session.id)
                  ? () => resetSessionAccent(props.mode, session.id)
                  : undefined
              }
            />
          )}
        </For>
      </Stack>
    </Stack>
  );
}

export function AppearanceSection(): JSX.Element {
  const theme = useTheme();
  // The accents are per mode, and only the visible one is editable — choosing a
  // colour you cannot see it applied to is guesswork. Switching the theme above
  // switches which palette these five fields address, which is also the fastest
  // way to reach the other one.
  const mode = () => theme.resolved;

  const resetAll = () => {
    const previous = resetAllAccents();
    toast.success("Accent colors reset", {
      action: { label: "Undo", onClick: () => restoreAccents(previous) },
    });
  };

  return (
    <Stack gap={4}>
      <Panel label="Appearance">
        <Row align="center" justify="between">
          <Stack gap={1}>
            <Text variant="label" tone="default">
              Theme
            </Text>
            <Text variant="micro" tone="dim">
              Phosphor (dark), Paper (light), or follow system. Stored locally
              on this device.
            </Text>
          </Stack>
          <ThemeToggle />
        </Row>
      </Panel>

      <Panel label="Accent colors">
        <Stack gap={3}>
          <Row align="center" justify="between">
            <Stack gap={1}>
              <Text variant="micro" tone="dim">
                Editing the {MODE_LABEL[mode()] ?? mode()} palette. Each mode
                keeps its own colors — switch the theme above to edit the other.
                Stored locally on this device.
              </Text>
            </Stack>
            {/* Reads `accentOverrides()` so the control appears and disappears
                with the state it acts on. */}
            <Show when={accentOverrides() && hasAccentOverrides()}>
              <Button variant="ghost" size="sm" onClick={resetAll}>
                Reset all
              </Button>
            </Show>
          </Row>

          <Divider />

          <Stack gap={3}>
            <For each={ACCENT_TOKENS}>
              {(spec) => (
                <Show
                  when={spec.token !== "accent"}
                  fallback={<SignatureRow spec={spec} mode={mode()} />}
                >
                  <ColorField
                    label={spec.label}
                    description={spec.description}
                    mode={mode()}
                    value={accentValue(mode(), spec.token)}
                    // Dragging the OS picker fires `input` continuously: repaint
                    // every frame, write to storage only when it settles.
                    onInput={(hex) =>
                      setAccent(mode(), spec.token, hex, { persist: false })
                    }
                    onChange={(hex) => setAccent(mode(), spec.token, hex)}
                    onReset={
                      isAccentOverridden(mode(), spec.token)
                        ? () => resetAccent(mode(), spec.token)
                        : undefined
                    }
                  />
                </Show>
              )}
            </For>
          </Stack>
        </Stack>
      </Panel>
    </Stack>
  );
}
