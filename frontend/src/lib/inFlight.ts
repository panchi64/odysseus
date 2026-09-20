import { createSignal, type Accessor } from "solid-js";

/**
 * Which *things* an operation is currently running against.
 *
 * Every long action in this app is about something — a conversation being folded, an MCP
 * server being dialled, a connector being tested, a corpus source being re-indexed — and
 * the controller holding the flag almost always outlives the thing. A boolean, or a
 * single id slot, then says three wrong things at once: it lights the throbber on
 * whichever row the operator has since moved to, it refuses a second row's action with no
 * visible reason, and the first run's cleanup clears the second run's flag.
 *
 * So the in-flight state is a **set keyed by the thing**, and the only question a caller
 * asks is "is *this* one running?". Four surfaces had hand-rolled a single slot and got
 * the same three symptoms; this is that shape, written once.
 *
 * `run` is the whole lifecycle — claim, execute, release — because the claim has to be
 * taken **synchronously, before the first await**. A guard that checks the set and then
 * awaits something before adding to it is not a guard: two rapid invocations both read an
 * empty set, both proceed, and the second meets whatever the first has already started.
 */
export interface InFlight<K extends string = string> {
  /** True while an operation is running against `key`. */
  has: (key: K) => boolean;
  /** True while anything at all is running — for the rare caller that is genuinely
   *  one-at-a-time rather than per-thing. */
  any: Accessor<boolean>;
  /**
   * Claim `key`, run `task`, release it — returning `undefined` without running when
   * `key` is already claimed. The claim is taken before `task` is even called, so the
   * guard holds across every await inside it.
   *
   * `task` owns its own failures: this re-throws so a caller that wants to react still
   * can, and releases either way.
   */
  run: <T>(key: K, task: () => Promise<T>) => Promise<T | undefined>;
}

export function createInFlight<K extends string = string>(): InFlight<K> {
  const [keys, setKeys] = createSignal<ReadonlySet<K>>(new Set());
  const mark = (key: K, active: boolean): void => {
    setKeys((prev) => {
      const next = new Set(prev);
      if (active) next.add(key);
      else next.delete(key);
      return next;
    });
  };
  return {
    has: (key) => keys().has(key),
    any: () => keys().size > 0,
    run: async (key, task) => {
      if (keys().has(key)) return undefined;
      mark(key, true);
      try {
        return await task();
      } finally {
        mark(key, false);
      }
    },
  };
}
