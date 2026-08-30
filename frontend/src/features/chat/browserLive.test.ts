import { describe, expect, it } from "bun:test";
import {
  applyMessage,
  closeNote,
  displayUrl,
  endBrowser,
  isFinal,
  NO_BROWSER,
  openBrowser,
  reconnecting,
} from "./browserLive";

const frameMessage = (over: Record<string, unknown> = {}) => ({
  t: "frame",
  data: "AAAA",
  w: 1280,
  h: 800,
  url: "https://example.com/app",
  title: "Example",
  tabs: 1,
  active: 0,
  ...over,
});

describe("opening a session", () => {
  it("starts clean on a new session", () => {
    const state = openBrowser(NO_BROWSER, "/browser/stream/tok");
    expect(state.streamPath).toBe("/browser/stream/tok");
    expect(state.status).toBe("streaming");
    expect(state.frame).toBeNull();
  });

  it("is a no-op when the same session is announced again", () => {
    // A turn calls a dozen browser tools; the panel must not reset a dozen times.
    const opened = openBrowser(NO_BROWSER, "/browser/stream/tok");
    const withFrame = applyMessage(opened, frameMessage());
    expect(openBrowser(withFrame, "/browser/stream/tok")).toBe(withFrame);
  });

  it("drops the old session's last frame when a new one replaces it", () => {
    // Otherwise the dead session's page would sit under the new session's URL.
    const withFrame = applyMessage(
      openBrowser(NO_BROWSER, "/browser/stream/old"),
      frameMessage(),
    );
    const fresh = openBrowser(withFrame, "/browser/stream/new");
    expect(fresh.frame).toBeNull();
    expect(fresh.status).toBe("streaming");
  });
});

describe("frames", () => {
  it("replaces rather than accumulating", () => {
    let state = openBrowser(NO_BROWSER, "/browser/stream/tok");
    state = applyMessage(state, frameMessage({ data: "first" }));
    state = applyMessage(state, frameMessage({ data: "second" }));
    expect(state.frame?.data).toBe("second");
  });

  it("carries metadata forward when a frame omits it", () => {
    // The backend refreshes url/title on its own tick, so a frame can arrive without
    // them; blanking the readout would make it flicker.
    let state = applyMessage(
      openBrowser(NO_BROWSER, "/browser/stream/tok"),
      frameMessage(),
    );
    state = applyMessage(state, { t: "frame", data: "next" });
    expect(state.frame).toMatchObject({
      data: "next",
      url: "https://example.com/app",
      title: "Example",
      width: 1280,
      height: 800,
    });
  });

  it("ignores malformed messages instead of tearing the panel down", () => {
    const state = applyMessage(
      openBrowser(NO_BROWSER, "/browser/stream/tok"),
      frameMessage(),
    );
    expect(applyMessage(state, { t: "frame" })).toBe(state);
    expect(applyMessage(state, { t: "nonsense" })).toBe(state);
    expect(applyMessage(state, {})).toBe(state);
  });

  it("clears a reconnecting note once frames resume", () => {
    let state = applyMessage(
      openBrowser(NO_BROWSER, "/browser/stream/tok"),
      frameMessage(),
    );
    state = reconnecting(state);
    expect(state.status).toBe("reconnecting");
    state = applyMessage(state, frameMessage({ data: "back" }));
    expect(state.status).toBe("streaming");
  });
});

describe("ending", () => {
  it("keeps the last frame as a still", () => {
    // The operator should still see where the agent left the page.
    const state = applyMessage(
      openBrowser(NO_BROWSER, "/browser/stream/tok"),
      frameMessage(),
    );
    const ended = applyMessage(state, { t: "end", reason: "stopped" });
    expect(ended.status).toBe("ended");
    expect(ended.frame?.data).toBe("AAAA");
    expect(ended.note).toBe("The agent's browser was closed.");
  });

  it("does not walk backwards from ended to reconnecting", () => {
    // The socket closing *after* an end message must not read as a dropped connection.
    const ended = endBrowser(NO_BROWSER, "done");
    expect(reconnecting(ended)).toBe(ended);
  });
});

describe("close codes", () => {
  it("tells a reaped session from an unknown one", () => {
    expect(closeNote(4410)).toBe("The agent's browser was closed.");
    expect(closeNote(4404)).toBe(
      "This browser session is no longer available.",
    );
    expect(closeNote(1011)).toBe("The browser stream was refused.");
  });

  it("treats an ordinary drop as retryable, not as a verdict", () => {
    expect(closeNote(1006)).toBeNull();
    expect(isFinal(1006)).toBe(false);
    expect(isFinal(4410)).toBe(true);
  });
});

describe("the URL readout", () => {
  it("shows host and path, dropping a bare root", () => {
    expect(displayUrl("https://example.com/")).toBe("example.com");
    expect(displayUrl("https://example.com/a/b?q=1")).toBe(
      "example.com/a/b?q=1",
    );
  });

  it("passes through what it cannot parse", () => {
    expect(displayUrl("about:blank")).toBe("about:blank");
    expect(displayUrl("")).toBe("");
  });
});
