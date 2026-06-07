import { createSignal, onCleanup, Show, type JSX } from "solid-js";
import {
  Button,
  LoadingText,
  Modal,
  Row,
  Stack,
  Text,
  Textarea,
  toast,
} from "~/ui";
import type { Skill } from "../model";

/** Run-a-skill test harness. Opens when `skill` is non-null. Shared by the
 *  skills directory and the skill editor so the test flow is identical. */
export function TestSkillModal(props: {
  skill: Skill | null;
  onClose: () => void;
}): JSX.Element {
  const [input, setInput] = createSignal("");
  const [running, setRunning] = createSignal(false);
  const [result, setResult] = createSignal<string | null>(null);

  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => timers.forEach(clearTimeout));

  function handleClose() {
    setInput("");
    setResult(null);
    setRunning(false);
    props.onClose();
  }

  function runTest() {
    if (!input().trim()) {
      toast.error(
        "Test input required — enter a sample prompt to test against.",
      );
      return;
    }
    setRunning(true);
    setResult(null);
    // Phase-1 mock: simulate execution then show a fake result
    timers.push(
      setTimeout(() => {
        setRunning(false);
        setResult(
          `[MOCK RESULT — Phase 1]\n\nSkill: ${props.skill?.name ?? "Unknown"}\nTrigger matched: "${props.skill?.trigger ?? ""}"\n\nOutput:\nThe assistant would execute the skill procedure with the provided input. In Phase 2, this will show the real model response.\n\nInput received:\n"${input().trim()}"`,
        );
      }, 1200),
    );
  }

  return (
    <Modal
      open={props.skill !== null}
      onClose={handleClose}
      title={`TEST — ${props.skill?.name ?? ""}`}
      class="max-w-lg"
      footer={
        <Row gap={2}>
          <Button variant="ghost" onClick={handleClose}>
            CLOSE
          </Button>
          <Button
            variant="primary"
            leading="play"
            onClick={runTest}
            disabled={running()}
          >
            {running() ? "RUNNING…" : "RUN TEST"}
          </Button>
        </Row>
      }
    >
      <Stack gap={4}>
        <div class="flex flex-col gap-2">
          <Text variant="label" tone="dim">
            SAMPLE INPUT
          </Text>
          <Textarea
            value={input()}
            onInput={(e) => setInput(e.currentTarget.value)}
            placeholder="Paste a sample message or prompt to test the trigger…"
            rows={4}
            disabled={running()}
          />
        </div>

        <Show when={running()}>
          <LoadingText />
        </Show>

        <Show when={result()}>
          <div class="flex flex-col gap-2">
            <Text variant="label" tone="dim">
              RESULT
            </Text>
            <div class="border border-line bg-raised p-3">
              <Text
                variant="body"
                class="whitespace-pre-wrap font-mono leading-relaxed"
              >
                {result()}
              </Text>
            </div>
          </div>
        </Show>
      </Stack>
    </Modal>
  );
}
