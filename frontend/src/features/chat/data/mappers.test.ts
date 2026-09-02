import { describe, expect, test } from "bun:test";
import { toMessage } from "./mappers";
import type { MessageDTO } from "./wire";

function divider(overrides: Partial<MessageDTO> = {}): MessageDTO {
  return {
    id: "chk-1",
    role: "compaction",
    content: "the story so far",
    tools: [],
    messages_compacted: 12,
    tokens_before: 62_000,
    tokens_after: 4_000,
    ...overrides,
  };
}

describe("toMessage decodes a compaction divider", () => {
  // The cold read is the *second* producer of this row — the live `conversation.compacted`
  // fold is the first — and the two have to agree, or a reload contradicts what the
  // operator just watched happen.
  test("the fold's cost and its reason both come across", () => {
    const m = toMessage(divider({ compaction_reason: "overflow" }));
    expect(m.foldedMessages).toBe(12);
    expect(m.tokensBefore).toBe(62_000);
    expect(m.tokensAfter).toBe(4_000);
    expect(m.compactionReason).toBe("overflow");
  });

  test("a checkpoint folded before reasons were stored decodes to none", () => {
    // Null is what the backend sends for a fold recorded before it wrote the reason onto
    // the checkpoint. It must not become a default: telling the operator the provider
    // forced a fold they asked for is worse than saying nothing.
    expect(
      toMessage(divider({ compaction_reason: null })).compactionReason,
    ).toBeUndefined();
    expect(toMessage(divider()).compactionReason).toBeUndefined();
  });

  test("a reason this build has no words for is dropped", () => {
    // The wire type is a plain string, so a newer backend naming a fourth trigger reaches
    // the mapper. Better an absent segment than a raw enum id in the divider's label.
    expect(
      toMessage(divider({ compaction_reason: "pressure" })).compactionReason,
    ).toBeUndefined();
  });

  test("an ordinary user turn carries no fold facts", () => {
    const m = toMessage({
      id: "m-1",
      role: "user",
      content: "hello",
      tools: [],
      messages_compacted: 0,
      tokens_before: 0,
      tokens_after: 0,
      compaction_reason: null,
    });
    expect(m.compactionReason).toBeUndefined();
    // The backend sends 0 rather than omitting these, which is why every consumer guards
    // on `> 0` — the mapper passes the zeros through rather than inventing absence.
    expect(m.foldedMessages).toBe(0);
  });
});
