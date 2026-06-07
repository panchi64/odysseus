import type { LeaderboardEntry } from "./model";

export const mockLeaderboard: LeaderboardEntry[] = [
  {
    model: "qwen2.5-coder-32b",
    wins: 14,
    losses: 3,
    total: 17,
    winRate: 0.824,
  },
  { model: "deepseek-r1-32b", wins: 11, losses: 6, total: 17, winRate: 0.647 },
  { model: "llama-3.3-70b", wins: 9, losses: 8, total: 17, winRate: 0.529 },
  { model: "phi-4-14b", wins: 6, losses: 11, total: 17, winRate: 0.353 },
  { model: "gemma-3-27b", wins: 4, losses: 13, total: 17, winRate: 0.235 },
];

/** Canned responses used by the mock streaming controller. Indexed by slot. */
export const mockResponses: Record<
  "A" | "B",
  { model: string; response: string }
> = {
  A: {
    model: "qwen2.5-coder-32b",
    response:
      "The key difference between `asyncio.gather` and `asyncio.TaskGroup` (Python 3.11+) is error propagation. `gather` by default cancels all remaining tasks when one fails if `return_exceptions=False`, but TaskGroup always cancels the group on first exception and then re-raises after all cancellations complete — making cleanup deterministic. For production code, prefer TaskGroup: the structured concurrency guarantee means you never accidentally leave orphaned coroutines running after a failure. Use `gather` only when you genuinely need to collect results from independent tasks where partial failure is acceptable and you handle it via `return_exceptions=True`.",
  },
  B: {
    model: "deepseek-r1-32b",
    response:
      "Both `asyncio.gather` and `asyncio.TaskGroup` run coroutines concurrently, but they have different cancellation semantics. With `gather(return_exceptions=False)`, a failing task causes gather to cancel and await the others, then raise the first exception. `TaskGroup` (3.11+) implements structured concurrency: the block doesn't exit until all tasks finish or are cancelled, and all exceptions are collected into an `ExceptionGroup`. This makes TaskGroup safer because tasks cannot outlive their enclosing scope. The practical rule: use TaskGroup for anything where you care about cleanup correctness; use gather when you need a flat list of results and are comfortable managing exceptions manually.",
  },
};
