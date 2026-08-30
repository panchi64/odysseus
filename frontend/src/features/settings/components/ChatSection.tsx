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
import { DEFAULT_WALL_CLOCK_S, wallClockMinutes } from "../model";

/** One preference's title and its explanation — the shape every block in this panel
 *  opens with. Extracted at the fourth copy: the wording is all that ever differed,
 *  and four hand-repeated `label`/`micro dim` pairs are four chances for one of them
 *  to drift to a different tone. */
function SettingHeader(props: {
  title: string;
  children: JSX.Element;
}): JSX.Element {
  return (
    <Stack gap={1}>
      <Text variant="label" tone="default">
        {props.title}
      </Text>
      <Text variant="micro" tone="dim">
        {props.children}
      </Text>
    </Stack>
  );
}

const Rule = (): JSX.Element => <div class="border-line border-t" />;

/** A whole number within `[min, max]`, or null when the field can't supply one —
 *  every editable value in this panel is one. `Number("")` is 0, so a blanked field has
 *  to be rejected explicitly rather than read as zero. */
function wholeNumber(
  raw: string,
  { min = 1, max = Number.MAX_SAFE_INTEGER } = {},
): number | null {
  const n = Number(raw.trim());
  if (raw.trim() === "" || !Number.isInteger(n) || n < min || n > max)
    return null;
  return n;
}

/** This panel's policy for a bound that isn't set: fall back to the shared seed, so
 *  switching the limit on and pressing Save writes something sensible instead of erroring
 *  on a blank field. The conversion itself is `wallClockMinutes`, shared with the
 *  palette so one stored bound never rounds to two different numbers. */
function minutesOr(seconds: number | null): number {
  return wallClockMinutes(seconds ?? DEFAULT_WALL_CLOCK_S);
}

/* Operator preferences for how a turn runs: how many model round-trips one turn may
   spend, how long it may go silent before the watchdog stops it, when the composer's
   context gauge starts showing colour, and the one context reduction there is — when
   whole earlier turns are folded into a summary. Each editable value seeds from the
   backend resource and saves back to it. */
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
  // How long (minutes) a run may take in total, however busy it is. Off unless the
  // operator switches it on — the step limit is what bounds a runaway turn, so this
  // exists for the case nothing else covers: a run that keeps emitting and so never
  // looks idle to the watchdog. Edited in minutes, stored in seconds.
  const [wallClockOn, setWallClockOn] = createSignal(false);
  const [wallClockMin, setWallClockMin] = createSignal("");
  const [savingWallClock, setSavingWallClock] = createSignal(false);
  // Conversation compaction: fold whole earlier turns into a summary once the context
  // window fills. The threshold is stored as a fraction and edited as a percentage — the
  // number the operator actually thinks in.
  const [autoCompactEnabled, setAutoCompactEnabled] = createSignal(true);
  const [autoCompactPct, setAutoCompactPct] = createSignal("");
  const [savingAutoCompact, setSavingAutoCompact] = createSignal(false);
  // Where the composer's context ring stops being grey. Two fractions, edited as
  // percentages and saved together, because the pair is only valid in order.
  const [warnPct, setWarnPct] = createSignal("");
  const [alertPct, setAlertPct] = createSignal("");
  const [savingContext, setSavingContext] = createSignal(false);
  createEffect(() => {
    const s = chatSettings();
    if (!s) return;
    setStepLimit(String(s.agentRequestLimit));
    setTimeoutS(String(s.inactivityTimeoutS));
    setWallClockOn(s.wallClockTimeoutS !== null);
    setWallClockMin(String(minutesOr(s.wallClockTimeoutS)));
    setAutoCompactEnabled(s.autoCompactEnabled);
    setAutoCompactPct(String(Math.round(s.autoCompactThreshold * 100)));
    setWarnPct(String(Math.round(s.contextWarnThreshold * 100)));
    setAlertPct(String(Math.round(s.contextAlertThreshold * 100)));
  });
  const saveSteps = async () => {
    const n = wholeNumber(stepLimit());
    // Floored at 1: a turn allowed zero model requests could never answer at all.
    if (n === null) {
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
    // Whole seconds, above 0: a 0 bound would stop every turn immediately, and the
    // backend rejects it too.
    const n = wholeNumber(timeoutS());
    if (n === null) {
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
  const saveWallClock = async () => {
    // Off sends `null` — a value the backend acts on (remove the bound), not an omission.
    // The minutes field is only read when the switch is on, so a blank one can't block
    // turning the limit off.
    const minutes = wallClockOn() ? wholeNumber(wallClockMin()) : null;
    if (wallClockOn() && minutes === null) {
      toast.error("Enter whole minutes (1 or more).");
      return;
    }
    setSavingWallClock(true);
    try {
      const saved = await saveChatSettings({
        wallClockTimeoutS: minutes === null ? null : minutes * 60,
      });
      setWallClockOn(saved.wallClockTimeoutS !== null);
      setWallClockMin(String(minutesOr(saved.wallClockTimeoutS)));
      toast.success("Total time limit updated");
    } catch {
      toast.error("Unable to update the total time limit.");
    } finally {
      setSavingWallClock(false);
    }
  };

  const saveAutoCompact = async () => {
    // Above 0 and at most 100: a 0% threshold would fire on an empty thread, and there is
    // nothing above "the window is full" to wait for.
    const pct = wholeNumber(autoCompactPct(), { max: 100 });
    if (pct === null) {
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

  const saveContextThresholds = async () => {
    // 99 is the ceiling on the warning, not 100: at 100 the amber band is unreachable,
    // since the ring would go straight to red on a full window.
    const warn = wholeNumber(warnPct(), { max: 99 });
    const alert = wholeNumber(alertPct(), { min: 2, max: 100 });
    if (warn === null || alert === null) {
      toast.error("Enter whole percentages — warning 1–99, alert 2–100.");
      return;
    }
    // Checked here for immediate feedback, and again by the backend, which owns the
    // rule: equal boundaries leave no amber band at all, and inverted ones walk the
    // gauge backwards through severity as the window fills.
    if (warn >= alert) {
      toast.error("The warning percentage must be below the alert percentage.");
      return;
    }
    setSavingContext(true);
    try {
      const saved = await saveChatSettings({
        contextWarnThreshold: warn / 100,
        contextAlertThreshold: alert / 100,
      });
      setWarnPct(String(Math.round(saved.contextWarnThreshold * 100)));
      setAlertPct(String(Math.round(saved.contextAlertThreshold * 100)));
      toast.success("Context gauge updated");
    } catch {
      toast.error("Unable to update the context gauge.");
    } finally {
      setSavingContext(false);
    }
  };

  return (
    <Panel label="Chat">
      <Show when={chatSettings()} fallback={<LoadingText />}>
        <Stack gap={3}>
          <SettingHeader title="Step limit per turn">
            How many times the model may be called within a single turn. Every
            tool call spends one, so a long research or multi-step turn is what
            runs this out — raise it for work that needs many steps, lower it to
            stop a runaway turn sooner. Mid-run messages you send continue the
            same turn and share its budget.
          </SettingHeader>
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
              {savingSteps() ? "Saving…" : "Save"}
            </Button>
          </Row>

          <Rule />

          <SettingHeader title="Inactivity timeout">
            How long a run may go without producing anything before it is
            stopped, in seconds. A long generation — a big file write, a slow
            first token — needs more than the default; raise it so a slow turn
            isn't cut off, or lower it to bail on a stuck one sooner.
          </SettingHeader>
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
              {savingTimeout() ? "Saving…" : "Save"}
            </Button>
          </Row>

          <Rule />

          <SettingHeader title="Total time limit">
            A ceiling on how long one turn may take start to finish, however
            busy it is. Off by default: the step limit above is what stops a
            runaway turn, so a clock mostly cuts off turns that are simply slow
            — a local model, a long tool call. Switch it on to catch what
            neither other limit does: a turn that keeps producing output — a
            tool reporting progress, a model still writing — and so never looks
            idle, no matter how long it goes on.
          </SettingHeader>
          <Toggle
            checked={wallClockOn()}
            onChange={setWallClockOn}
            label="Stop a turn once it has run this long"
          />
          <Row gap={4} align="end">
            <Stack gap={1}>
              <Text variant="micro" tone="dim">
                STOP AFTER (minutes)
              </Text>
              <div class="w-48">
                <Input
                  type="number"
                  inputMode="numeric"
                  min="1"
                  value={wallClockMin()}
                  onInput={(e) => setWallClockMin(e.currentTarget.value)}
                  placeholder={String(minutesOr(null))}
                  disabled={!wallClockOn()}
                />
              </div>
            </Stack>
            <Button
              variant="primary"
              disabled={savingWallClock()}
              onClick={() => void saveWallClock()}
            >
              {savingWallClock() ? "Saving…" : "Save"}
            </Button>
          </Row>

          <Rule />

          <SettingHeader title="Context gauge">
            The ring beside Send shows how full the model's context window is.
            It stays grey while there's room, turns amber at the first
            percentage, and red at the second — so it only catches your eye when
            it has something to say. Lower them if your turns are long enough
            that a nearly-full window runs out in one go; raise them if the ring
            colours earlier than you need it to.
          </SettingHeader>
          <Row gap={4} align="end">
            <Stack gap={1}>
              <Text variant="micro" tone="dim">
                AMBER AT (% of context)
              </Text>
              <div class="w-32">
                <Input
                  type="number"
                  inputMode="numeric"
                  min="1"
                  max="99"
                  value={warnPct()}
                  onInput={(e) => setWarnPct(e.currentTarget.value)}
                  placeholder="75"
                />
              </div>
            </Stack>
            <Stack gap={1}>
              <Text variant="micro" tone="dim">
                RED AT (% of context)
              </Text>
              <div class="w-32">
                <Input
                  type="number"
                  inputMode="numeric"
                  min="2"
                  max="100"
                  value={alertPct()}
                  onInput={(e) => setAlertPct(e.currentTarget.value)}
                  placeholder="90"
                />
              </div>
            </Stack>
            <Button
              variant="primary"
              disabled={savingContext()}
              onClick={() => void saveContextThresholds()}
            >
              {savingContext() ? "Saving…" : "Save"}
            </Button>
          </Row>

          <Rule />

          <SettingHeader title="Auto-compact conversations">
            When a conversation nears the model's context limit, its earlier
            turns are folded into a summary and the chat carries on instead of
            stopping. The most recent exchanges are kept word for word, and your
            transcript keeps everything — only what the model re-reads is
            condensed. Off, a full conversation stops at the limit and you start
            a new one or rewind.
          </SettingHeader>
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
              {savingAutoCompact() ? "Saving…" : "Save"}
            </Button>
          </Row>
        </Stack>
      </Show>
    </Panel>
  );
}
