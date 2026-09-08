/**
 * Does a streamed answer leave anything behind?
 *
 * The reveal wraps each arriving character in its own span so it can resolve in on its
 * own schedule, and for a long time nothing ever took those wrappers out again: every
 * character that passed through the reveal window kept its span, its inline
 * `animation-delay` and its filled animation for the life of the session. A four-turn
 * fixture left over a thousand of them. That is invisible — the fade is over, the text
 * reads correctly — and it is paid on every repaint of a scrolling transcript, both in
 * the extra elements and in text that is shaped one character at a time.
 *
 * So the assertion is the one thing no unit test can see: after a stream ends, the DOM
 * holds no reveal wrappers and the answer still reads exactly as its source. The pure
 * scheduling rules behind it are covered in `streamReveal.test.ts`; this is the check
 * that the DOM half actually runs.
 *
 * It drives `/bench` (dev-only, no auth, no backend, synthetic content) through
 * `__bench.pump()` rather than through frames, because `requestAnimationFrame` does not
 * fire in a headless WebView.
 *
 * Excluded from `bun run test`; `bun run test:smoke` runs it.
 */
import { afterAll, beforeAll, expect, test } from "bun:test";
import { join } from "node:path";

const PORT = 39_882;
const ORIGIN = `http://localhost:${PORT}`;
const FRONTEND_ROOT = join(import.meta.dir, "..", "..", "..");

let dev: ReturnType<typeof Bun.spawn> | undefined;

async function waitFor(
  what: string,
  check: () => Promise<boolean>,
  timeoutMs: number,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown;
  while (Date.now() < deadline) {
    try {
      if (await check()) return;
    } catch (error) {
      lastError = error;
    }
    await Bun.sleep(250);
  }
  throw new Error(
    `timed out after ${timeoutMs}ms waiting for ${what}` +
      (lastError ? ` (last error: ${lastError})` : ""),
  );
}

beforeAll(async () => {
  dev = Bun.spawn(
    ["bun", "run", "dev", "--port", String(PORT), "--strictPort"],
    {
      cwd: FRONTEND_ROOT,
      stdout: "pipe",
      stderr: "pipe",
      env: { ...process.env, BROWSER: "none" },
    },
  );
  await waitFor(
    "the dev server to serve",
    async () => (await fetch(ORIGIN)).ok,
    90_000,
  );
});

afterAll(() => {
  dev?.kill();
});

test("a streamed answer leaves no reveal wrappers behind", async () => {
  const wv = new Bun.WebView({ headless: true });
  try {
    await wv.navigate(`${ORIGIN}/bench?mode=streamed&n=4`);
    await waitFor(
      "the bench to mount",
      async () => Boolean(await wv.evaluate("Boolean(window.__bench)")),
      30_000,
    );

    // `pump` resolves with the most wrappers that were in the DOM at once. Asserting on
    // it is what stops the check below from going vacuous: a reveal that stopped
    // wrapping anything at all would end with zero wrappers too, and look like a pass.
    // The peak is sampled inside the page because polling for it from out here races
    // the terminal flush.
    await wv.evaluate("window.__bench.pump().then((n) => (window.__peak = n))");
    // Waits on `__peak` itself, not on `ready()`. They are not the same signal: `step()`
    // flips `ready` and only then lets `pump` resolve, so a poll that sees `ready()` is
    // not yet proof the peak has been assigned — a race the IPC round-trip happens to
    // hide today and would stop hiding on a faster transport.
    await waitFor(
      "the fixture to finish streaming",
      async () => Boolean(await wv.evaluate("window.__peak !== undefined")),
      30_000,
    );
    expect(Number(await wv.evaluate("window.__peak"))).toBeGreaterThan(0);

    // The terminal flush is on a timer keyed to the last character's fade, so this
    // waits on the condition rather than guessing at the duration.
    await waitFor(
      "the reveal wrappers to be taken back out",
      async () =>
        Number(await wv.evaluate("window.__bench.counts().revealSpans")) === 0,
      10_000,
    );

    // Unwrapping rewrites text nodes, so the other half of the check is that it put
    // back exactly what it took: same characters, and re-joined into whole runs rather
    // than left one node per character (which is what costs the shaping).
    const text = String(
      await wv.evaluate("document.querySelector('.ody-prose').textContent"),
    );
    expect(text).toContain("The fence holds the process to the declaration");

    // Measured on the LAST block, and that is load-bearing. Every earlier block is
    // re-rendered from source the moment a block after it begins — `Markdown`'s `<For>`
    // sees a changed raw string — so it ends up with whole text runs whether or not
    // anything re-joined them. The final block is the only one that keeps its wrappers
    // until the terminal flush, so it is the only one where the re-join is observable.
    const longestRun = Number(
      await wv.evaluate(
        "(() => {" +
          " const blocks = document.querySelectorAll('.ody-prose > [data-block-index]');" +
          " const last = blocks[blocks.length - 1];" +
          " const runs = [...last.querySelector('p').childNodes]" +
          "   .filter((n) => n.nodeType === 3).map((n) => n.data.length);" +
          " return Math.max(...runs);" +
          "})()",
      ),
    );
    expect(longestRun).toBeGreaterThan(20);
  } finally {
    wv.close();
  }
}, 180_000);
