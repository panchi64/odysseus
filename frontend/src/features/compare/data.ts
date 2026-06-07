import {
  createResource,
  createSignal,
  onCleanup,
  type Resource,
} from "solid-js";
import { createStore, produce } from "solid-js/store";
import type { CompareCandidate, CompareRun, LeaderboardEntry } from "./model";
import { mockLeaderboard, mockResponses } from "./mocks";

/* ── Read accessors (the seam) ─────────────────────────────────────────────── */

async function fetchLeaderboard(): Promise<LeaderboardEntry[]> {
  return mockLeaderboard;
}

export function useLeaderboard(): Resource<LeaderboardEntry[]> {
  const [data] = createResource(fetchLeaderboard);
  return data;
}

/* ── Compare run controller ─────────────────────────────────────────────────
   Drives blind comparison streaming. Phase 2: swap timer-based token delivery
   for two parallel SSE streams from the inference endpoint. */

let runCounter = 0;

export function createCompareRun() {
  const [run, setRun] = createStore<CompareRun>({
    id: "",
    prompt: "",
    candidates: [],
    revealed: false,
    winner: undefined,
  });
  const [active, setActive] = createSignal(false);

  const timers: ReturnType<typeof setTimeout>[] = [];
  const after = (ms: number, fn: () => void) => timers.push(setTimeout(fn, ms));

  function start(prompt: string) {
    if (!prompt.trim() || active()) return;
    setActive(true);
    runCounter++;

    const initial: CompareCandidate[] = [
      {
        slot: "A",
        model: mockResponses.A.model,
        response: "",
        streaming: true,
      },
      {
        slot: "B",
        model: mockResponses.B.model,
        response: "",
        streaming: true,
      },
    ];

    setRun(
      produce((r) => {
        r.id = `cmp-${runCounter}`;
        r.prompt = prompt.trim();
        r.candidates = initial;
        r.revealed = false;
        r.winner = undefined;
      }),
    );

    // Stream both responses in parallel with slight offsets
    (["A", "B"] as const).forEach((slot, slotIdx) => {
      const words = mockResponses[slot].response.split(" ");
      const baseOffset = slotIdx * 120; // slight stagger between columns

      words.forEach((_, i) =>
        after(baseOffset + i * 22, () => {
          setRun(
            produce((r) => {
              const cand = r.candidates.find((c) => c.slot === slot);
              if (cand) cand.response = words.slice(0, i + 1).join(" ");
            }),
          );
        }),
      );

      after(baseOffset + words.length * 22 + 60, () => {
        setRun(
          produce((r) => {
            const cand = r.candidates.find((c) => c.slot === slot);
            if (cand) cand.streaming = false;
          }),
        );
        if (slot === "B") setActive(false);
      });
    });
  }

  function vote(slot: "A" | "B") {
    if (run.revealed) return;
    setRun(
      produce((r) => {
        r.winner = slot;
        r.revealed = true;
      }),
    );
  }

  function reset() {
    timers.forEach(clearTimeout);
    timers.length = 0;
    setActive(false);
    setRun(
      produce((r) => {
        r.id = "";
        r.prompt = "";
        r.candidates = [];
        r.revealed = false;
        r.winner = undefined;
      }),
    );
  }

  onCleanup(() => timers.forEach(clearTimeout));

  return { run, active, start, vote, reset };
}
