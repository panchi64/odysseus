import { describe, expect, it } from "bun:test";
import { toWsUrl } from "./config";

describe("toWsUrl", () => {
  it("matches the socket scheme to the base's", () => {
    // A page served over TLS cannot open a plain `ws:` socket — the browser refuses it —
    // so this mapping is what makes the panel work anywhere but localhost.
    expect(toWsUrl("http://127.0.0.1:8000", "/browser/stream/tok")).toBe(
      "ws://127.0.0.1:8000/browser/stream/tok",
    );
    expect(toWsUrl("https://api.example.com", "/browser/stream/tok")).toBe(
      "wss://api.example.com/browser/stream/tok",
    );
  });

  it("keeps a base's path prefix without doubling the slash", () => {
    expect(toWsUrl("https://example.com/api/", "/browser/stream/tok")).toBe(
      "wss://example.com/api/browser/stream/tok",
    );
  });

  it("resolves a relative base against the page it is served from", () => {
    // A same-origin deployment sets no absolute base; the socket has to follow the app.
    expect(
      toWsUrl("/", "/browser/stream/tok", "https://app.example.com/chat"),
    ).toBe("wss://app.example.com/browser/stream/tok");
  });
});
