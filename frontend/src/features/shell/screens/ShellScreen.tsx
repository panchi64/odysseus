import { For, onCleanup, onMount, type JSX } from "solid-js";
import type { ShellLine } from "../model";
import {
  Button,
  Icon,
  PageHeader,
  Panel,
  Row,
  Stack,
  StatusFlag,
  Text,
  confirm,
  toast,
} from "~/ui";
import { createShellSession, isDangerousCommand } from "../data";

export function ShellScreen(): JSX.Element {
  const {
    lines,
    input,
    setInput,
    running,
    cancel,
    history,
    historyIdx,
    setHistoryIdx,
    run,
  } = createShellSession();

  let scrollRef: HTMLDivElement | undefined;
  let inputRef: HTMLInputElement | undefined;

  function scrollToBottom() {
    if (scrollRef) scrollRef.scrollTop = scrollRef.scrollHeight;
  }

  // Re-entrancy guard: blocks a second submit while the confirm dialog is open.
  let confirming = false;

  async function runCommand() {
    const cmd = input().trim();
    if (!cmd || running() || confirming) return;

    // Gate destructive commands behind an explicit confirmation.
    if (isDangerousCommand(cmd)) {
      confirming = true;
      const ok = await confirm({
        title: `Run this command?`,
        detail: `"${cmd}" — This action cannot be undone.`,
        confirmLabel: "RUN",
        tone: "alert",
      });
      confirming = false;
      if (!ok) {
        toast.warn("Command cancelled.");
        return;
      }
    }

    run(cmd, scrollToBottom);
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter") {
      void runCommand();
    } else if (e.key === "Escape") {
      if (input().length > 0) {
        // Clear input on first Escape.
        setInput("");
        setHistoryIdx(-1);
      } else {
        // Unfocus on second Escape (empty field).
        inputRef?.blur();
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const h = history();
      const idx = Math.min(historyIdx() + 1, h.length - 1);
      setHistoryIdx(idx);
      if (h[idx]) setInput(h[idx]);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      const idx = Math.max(historyIdx() - 1, -1);
      setHistoryIdx(idx);
      setInput(idx >= 0 ? (history()[idx] ?? "") : "");
    }
  }

  /** Global Ctrl+C handler: cancel a running command. */
  function handleGlobalKeyDown(e: KeyboardEvent) {
    if (e.ctrlKey && e.key === "c" && running()) {
      e.preventDefault();
      cancel();
      toast.warn("Interrupt sent — awaiting process exit.");
    }
  }

  onMount(() => {
    inputRef?.focus();
    window.addEventListener("keydown", handleGlobalKeyDown);
  });
  onCleanup(() => window.removeEventListener("keydown", handleGlobalKeyDown));

  const toneClass = (kind: ShellLine["kind"]) => {
    if (kind === "command") return "text-bright";
    if (kind === "stderr") return "text-alert";
    return "text-dim";
  };

  const prefixFor = (kind: ShellLine["kind"]) => {
    if (kind === "command") return "$ ";
    return "  ";
  };

  return (
    <Stack gap={6} class="flex h-full min-h-0 flex-col">
      <PageHeader
        title="HOST SHELL"
        subtitle="Execute commands directly on the server host. Administrator only."
        assetId="ODY-ADM-07.0 EDITION 01"
        actions={
          <Row gap={2} align="center">
            <StatusFlag status={running() ? "warn" : "nominal"} dot>
              {running() ? "RUNNING" : "READY"}
            </StatusFlag>
            {running() && (
              <Text variant="micro" tone="dim" class="select-none">
                Ctrl+C to interrupt
              </Text>
            )}
          </Row>
        }
      />

      <div class="flex min-h-0 flex-1 flex-col gap-3">
        {/* Danger notice */}
        <div class="flex items-center gap-2 border border-alert px-3 py-2">
          <Icon name="warning" size={12} class="text-alert shrink-0" />
          <Text variant="micro" tone="alert">
            Commands execute on the host machine with server-process privileges.
            Admin only. No undo.
          </Text>
        </div>

        {/* Scrollback output */}
        <Panel label="TERMINAL" class="flex min-h-0 flex-1 flex-col" flush>
          <div
            ref={scrollRef}
            class="min-h-0 flex-1 overflow-auto p-3 font-mono"
            style={{
              "max-height": "calc(100vh - 360px)",
              "min-height": "280px",
            }}
          >
            <For each={lines}>
              {(line) => (
                <div
                  class={`flex gap-2 py-0.5 leading-5 text-body ${toneClass(line.kind)}`}
                >
                  <span class="select-none text-dim shrink-0">
                    {prefixFor(line.kind)}
                  </span>
                  <span class="break-all">{line.text}</span>
                </div>
              )}
            </For>
          </div>

          {/* Command input */}
          <div class="border-t border-line px-3 py-2">
            <Row gap={2} align="center">
              <Text
                variant="label"
                tone="dim"
                class="select-none font-mono shrink-0"
              >
                $
              </Text>
              <input
                ref={inputRef}
                type="text"
                value={input()}
                onInput={(e) => setInput(e.currentTarget.value)}
                onKeyDown={handleKeyDown}
                disabled={running()}
                placeholder="enter command…"
                class="flex-1 bg-transparent font-mono text-body text-bright outline-none placeholder:text-dim disabled:opacity-40"
                spellcheck={false}
                autocomplete="off"
              />
              <Button
                variant="primary"
                size="sm"
                leading="play"
                onClick={() => void runCommand()}
                disabled={!input().trim() || running()}
              >
                RUN
              </Button>
            </Row>
          </div>
        </Panel>

        <Row gap={2} align="center">
          <Icon name="clock" size={12} class="text-dim" />
          <Text variant="micro" tone="dim">
            HISTORY: {history().length} commands this session · Use ↑/↓ to
            navigate
          </Text>
        </Row>
      </div>
    </Stack>
  );
}
