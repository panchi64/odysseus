/**
 * Does the auth gate render in place, or does it still redirect?
 *
 * This is the regression behind "I have to refresh the page every time I log in".
 * The gate used to `<Navigate>` to `/login`, which made unlocking a router
 * transition — and Solid commits a transition only once every resource read in the
 * new tree has settled, with no fallback shown meanwhile. The shell's cold
 * `/projects` and `/conversations` reads pinned it, so the login form stayed on
 * screen until the page was reloaded by hand.
 *
 * What is asserted is the structural fact that removes that whole class of bug: a
 * locked workspace shows its unlock screen **at the URL the operator asked for**,
 * with no navigation. If a redirect ever comes back, the pathname moves and this
 * fails.
 *
 * It runs with or without the Python backend, because `locked` is what both give:
 * with nothing to answer `/auth/status` the boot probe exhausts its backoff and
 * settles there, and a backend that *does* answer still classifies a fresh browser
 * — no stored token — as locked. Excluded from `bun run test`; `bun run test:smoke`
 * runs it.
 */
import { afterAll, beforeAll, expect, test } from "bun:test";
import { join } from "node:path";

const PORT = 39_884;
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

test("a locked workspace shows its unlock screen without navigating", async () => {
  const wv = new Bun.WebView({ headless: true });
  try {
    await wv.navigate(`${ORIGIN}/`);

    await waitFor(
      "the unlock screen",
      async () =>
        String(await wv.evaluate("document.body.innerText"))
          .toLowerCase()
          .includes("workspace locked"),
      30_000,
    );

    // The whole point: still at `/`. A redirect to `/login` is what put the app
    // one route transition away from its cold resources.
    expect(String(await wv.evaluate("location.pathname"))).toBe("/");
    expect(
      Number(
        await wv.evaluate(
          "document.querySelectorAll('input[type=password]').length",
        ),
      ),
    ).toBe(1);
  } finally {
    wv.close();
  }
}, 120_000);

test("/login is still a live URL, and lands on the same in-place gate", async () => {
  const wv = new Bun.WebView({ headless: true });
  try {
    await wv.navigate(`${ORIGIN}/login`);

    await waitFor(
      "the unlock screen",
      async () =>
        String(await wv.evaluate("document.body.innerText"))
          .toLowerCase()
          .includes("workspace locked"),
      30_000,
    );

    // A bookmark must not dead-end — it forwards home, where the gate takes over.
    expect(String(await wv.evaluate("location.pathname"))).toBe("/");
  } finally {
    wv.close();
  }
}, 120_000);
