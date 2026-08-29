import { describe, expect, test } from "bun:test";
import { sendBlocker } from "./sendGate";

/* The frontend half of the backend's send gate. Without a context window every
   mechanism that keeps a thread inside its limit is inert, so the backend refuses the
   turn (422); this is the same stop arriving before the operator commits a message to
   it. The two states below look identical from the window alone, which is the whole
   reason the decision is a function rather than a `?:` at the call site. */
describe("sendBlocker", () => {
  test("blocks a configured model whose window could not be established", () => {
    const reason = sendBlocker(true, null);
    expect(reason).not.toBeNull();
    expect(reason).toContain("context window");
  });

  test("allows a configured model with a window, however it was arrived at", () => {
    // Discovered or operator-set: by this point they are the same number.
    expect(sendBlocker(true, 262144)).toBeNull();
    expect(sendBlocker(true, 8192)).toBeNull();
  });

  test("stays silent when nothing is configured at all", () => {
    // An empty workspace has no window either, but telling someone their endpoint
    // doesn't report one before they have added an endpoint talks over the state that
    // actually needs fixing.
    expect(sendBlocker(false, null)).toBeNull();
  });

  test("says what to do, not just that something is wrong", () => {
    // The operator is the only one who can clear this, and only if the message names
    // the place — a bare "cannot send" leaves them hunting through settings.
    expect(sendBlocker(true, null)).toContain("Settings");
  });
});
