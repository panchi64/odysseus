import { createEffect, createSignal, Show, type JSX } from "solid-js";
import {
  Button,
  Input,
  LoadingText,
  Panel,
  Row,
  Stack,
  Text,
  Toggle,
  toast,
} from "~/ui";
import { saveChatSettings, useChatSettings } from "../data";

/* Operator preferences for how a turn runs: how many model round-trips one turn may
   spend, how long it may go silent before the watchdog stops it, and the one context
   reduction there is — when whole earlier turns are folded into a summary. Each
   editable value seeds from the backend resource and saves back to it. */
export function ChatSection(): JSX.Element {
  const chatSettings = useChatSettings();
  // How many model round-trips one turn may spend. Every tool call costs one, so this is
  // the ceiling a long tool-using turn actually stops at.
  const [stepLimit, setStepLimit] = createSignal("");
  const [savingSteps, setSavingSteps] = createSignal(false);
  // How long (seconds) a run may go silent before the watchdog stops it — the bound a
  // long generation (a big write, a slow first token) needs raised to stay alive.
  const [timeoutS, setTimeoutS] = createSignal("");
  const [savingTimeout, setSavingTimeout] = createSignal(false);
  // Conversation compaction: fold whole earlier turns into a summary once the context
  // window fills. The threshold is stored as a fraction and edited as a percentage — the
  // number the operator actually thinks in.
  const [autoCompactEnabled, setAutoCompactEnabled] = createSignal(true);
  const [autoCompactPct, setAutoCompactPct] = createSignal("");
  const [savingAutoCompact, setSavingAutoCompact] = createSignal(false);
  createEffect(() => {
    const s = chatSettings();
    if (!s) return;
    setStepLimit(String(s.agentRequestLimit));
    setTimeoutS(String(s.inactivityTimeoutS));
    setAutoCompactEnabled(s.autoCompactEnabled);
    setAutoCompactPct(String(Math.round(s.autoCompactThreshold * 100)));
  });
  const saveSteps = async () => {
    const raw = stepLimit().trim();
    const n = Number(raw);
    // Floored at 1: a turn allowed zero model requests could never answer at all.
    // `Number("")` is 0, so a blanked field is rejected explicitly rather than saved.
    if (raw === "" || !Number.isInteger(n) || n < 1) {
      toast.error("Enter a whole number of steps (1 or more).");
      return;
    }
    setSavingSteps(true);
    try {
      const saved = await saveChatSettings({ agentRequestLimit: n });
      setStepLimit(String(saved.agentRequestLimit));
      toast.success("Step limit updated");
    } catch {
      toast.error("Unable to update the step limit.");
    } finally {
      setSavingSteps(false);
    }
  };
  const saveTimeout = async () => {
    const raw = timeoutS().trim();
    const n = Number(raw);
    // Whole seconds, above 0: a 0 bound would stop every turn immediately, and the
    // backend rejects it too.
    if (raw === "" || !Number.isInteger(n) || n < 1) {
      toast.error("Enter whole seconds (1 or more).");
      return;
    }
    setSavingTimeout(true);
    try {
      const saved = await saveChatSettings({ inactivityTimeoutS: n });
      setTimeoutS(String(saved.inactivityTimeoutS));
      toast.success("Inactivity timeout updated");
    } catch {
      toast.error("Unable to update the inactivity timeout.");
    } finally {
      setSavingTimeout(false);
    }
  };

  const saveAutoCompact = async () => {
    const raw = autoCompactPct().trim();
    const pct = Number(raw);
    // Above 0 and at most 100: a 0% threshold would fire on an empty thread, and there is
    // nothing above "the window is full" to wait for.
    if (raw === "" || !Number.isInteger(pct) || pct < 1 || pct > 100) {
      toast.error("Enter a whole percentage between 1 and 100.");
      return;
    }
    setSavingAutoCompact(true);
    try {
      const saved = await saveChatSettings({
        autoCompactEnabled: autoCompactEnabled(),
        autoCompactThreshold: pct / 100,
      });
      setAutoCompactEnabled(saved.autoCompactEnabled);
      setAutoCompactPct(String(Math.round(saved.autoCompactThreshold * 100)));
      toast.success("Auto-compaction updated");
    } catch {
      toast.error("Unable to update auto-compaction settings.");
    } finally {
      setSavingAutoCompact(false);
    }
  };

  return (
    <Panel label="CHAT">
      <Show when={chatSettings()} fallback={<LoadingText />}>
        <Stack gap={3}>
          <Stack gap={1}>
            <Text variant="label" tone="default">
              STEP LIMIT PER TURN
            </Text>
            <Text variant="micro" tone="dim">
              How many times the model may be called within a single turn. Every
              tool call spends one, so a long research or multi-step turn is
              what runs this out — raise it for work that needs many steps,
              lower it to stop a runaway turn sooner. Mid-run messages you send
              continue the same turn and share its budget.
            </Text>
          </Stack>
          <Row gap={2} align="center">
            <div class="w-48">
              <Input
                type="number"
                inputMode="numeric"
                min="1"
                value={stepLimit()}
                onInput={(e) => setStepLimit(e.currentTarget.value)}
                placeholder="25"
              />
            </div>
            <Button
              variant="primary"
              disabled={savingSteps()}
              onClick={() => void saveSteps()}
            >
              {savingSteps() ? "SAVING…" : "SAVE"}
            </Button>
          </Row>

          <div class="border-line border-t" />

          <Stack gap={1}>
            <Text variant="label" tone="default">
              INACTIVITY TIMEOUT
            </Text>
            <Text variant="micro" tone="dim">
              How long a run may go without producing anything before it is
              stopped, in seconds. A long generation — a big file write, a slow
              first token — needs more than the default; raise it so a slow turn
              isn't cut off, or lower it to bail on a stuck one sooner.
            </Text>
          </Stack>
          <Row gap={2} align="center">
            <div class="w-48">
              <Input
                type="number"
                inputMode="numeric"
                min="1"
                value={timeoutS()}
                onInput={(e) => setTimeoutS(e.currentTarget.value)}
                placeholder="120"
              />
            </div>
            <Button
              variant="primary"
              disabled={savingTimeout()}
              onClick={() => void saveTimeout()}
            >
              {savingTimeout() ? "SAVING…" : "SAVE"}
            </Button>
          </Row>

          <div class="border-line border-t" />

          <Stack gap={1}>
            <Text variant="label" tone="default">
              AUTO-COMPACT CONVERSATIONS
            </Text>
            <Text variant="micro" tone="dim">
              When a conversation nears the model's context limit, its earlier
              turns are folded into a summary and the chat carries on instead of
              stopping. The most recent exchanges are kept word for word, and
              your transcript keeps everything — only what the model re-reads is
              condensed. Off, a full conversation stops at the limit and you
              start a new one or rewind.
            </Text>
          </Stack>
          <Toggle
            checked={autoCompactEnabled()}
            onChange={setAutoCompactEnabled}
            label="Fold older turns into a summary when the context fills"
          />
          <Row gap={4} align="end">
            <Stack gap={1}>
              <Text variant="micro" tone="dim">
                TRIGGER AT (% of context)
              </Text>
              <div class="w-32">
                <Input
                  type="number"
                  inputMode="numeric"
                  min="1"
                  max="100"
                  value={autoCompactPct()}
                  onInput={(e) => setAutoCompactPct(e.currentTarget.value)}
                  placeholder="95"
                  disabled={!autoCompactEnabled()}
                />
              </div>
            </Stack>
            <Button
              variant="primary"
              disabled={savingAutoCompact()}
              onClick={() => void saveAutoCompact()}
            >
              {savingAutoCompact() ? "SAVING…" : "SAVE"}
            </Button>
          </Row>
        </Stack>
      </Show>
    </Panel>
  );
}
