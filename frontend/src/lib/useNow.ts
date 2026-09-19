import { createSignal, onCleanup, type Accessor } from "solid-js";

/** The wall clock as a reactive value, shared by every consumer on the same cadence.
 *
 *  For readouts whose input is "how long since <backend timestamp>" — the mission
 *  clocks (§10.16). The elapsed figure is `useNow() - Date.parse(startedAt)`, which is
 *  a derivation over a value the backend owns, not state this layer holds: nothing here
 *  decides when anything began, and a clock is the easiest place in an interface to
 *  accidentally start.
 *
 *  **Shared and ref-counted, not one timer per clock.** A room with a session clock, a
 *  run clock and a sequencer full of rows would otherwise arm a dozen intervals that all
 *  fire within a few milliseconds of each other, waking the main thread a dozen times to
 *  compute the same `Date.now()` — and, because they drift apart, repainting the row
 *  clocks at visibly different instants. One timer per cadence means every clock on
 *  screen advances on the same frame, which is also what makes a column of them read as
 *  a single instrument rather than as a dozen independent ones.
 *
 *  The timer only exists while something is reading it: the last consumer to unmount
 *  clears it, and the next to mount starts a fresh one seeded with the current time, so
 *  a clock mounted between ticks is never up to a second stale on its first paint.
 */
const tickers = new Map<
  number,
  {
    now: Accessor<number>;
    set: (v: number) => void;
    id: number;
    readers: number;
  }
>();

export function useNow(intervalMs = 1000): Accessor<number> {
  let entry = tickers.get(intervalMs);

  if (!entry) {
    const [now, set] = createSignal(Date.now());
    // Re-read the clock on every tick rather than accumulating the interval:
    // setInterval drifts, and a throttled background tab drops ticks outright.
    // Reading the real time each time means a clock is correct on the first tick
    // after the tab wakes, rather than however far behind the dropped ticks left it.
    const id = setInterval(
      () => set(Date.now()),
      intervalMs,
    ) as unknown as number;
    entry = { now, set, id, readers: 0 };
    tickers.set(intervalMs, entry);
  } else {
    // A late joiner should not wait up to `intervalMs` to show the right time.
    entry.set(Date.now());
  }

  const active = entry;
  active.readers += 1;

  onCleanup(() => {
    active.readers -= 1;
    if (active.readers <= 0) {
      clearInterval(active.id);
      tickers.delete(intervalMs);
    }
  });

  return active.now;
}
