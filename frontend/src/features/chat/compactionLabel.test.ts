import { describe, expect, test } from "bun:test";
import { approxTokens, compactionLabel } from "./compactionLabel";
import type { ChatMessage } from "./model";

function divider(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "chk-1",
    role: "compaction",
    content: "the story so far",
    createdAt: "2026-01-01T00:00:00Z",
    foldedMessages: 14,
    tokensBefore: 62_000,
    tokensAfter: 4_000,
    ...overrides,
  };
}

describe("the divider's label", () => {
  test("a full fold reads as cause, count, then the replacement", () => {
    expect(compactionLabel(divider({ compactionReason: "manual" }))).toBe(
      "Context compacted · You asked · 14 Messages FOLDED · ~62k → ~4k",
    );
  });

  test("it reads correctly with no reason to name", () => {
    // The reason is the one segment that can be genuinely missing (a thread folded before
    // the backend recorded one), so the sentence has to stand without it — no stranded
    // separator, no blank between two `·`.
    const label = compactionLabel(divider());
    expect(label).toBe("Context compacted · 14 Messages FOLDED · ~62k → ~4k");
    expect(label).not.toContain("··");
    expect(label.endsWith("·")).toBe(false);
  });

  test("a reason the client cannot word is dropped rather than printed", () => {
    expect(
      compactionLabel(
        divider({
          compactionReason: "pressure" as ChatMessage["compactionReason"],
        }),
      ),
    ).toBe("Context compacted · 14 Messages FOLDED · ~62k → ~4k");
  });

  test("zeros are absent segments, not printed ones", () => {
    // The backend always sends the three counts, using 0 for "nothing to report" — so a
    // fold whose estimate rounds away must not put `~0 → ~0` on screen, which is a number
    // that answers no question.
    expect(
      compactionLabel(
        divider({ foldedMessages: 0, tokensBefore: 0, tokensAfter: 0 }),
      ),
    ).toBe("Context compacted");
  });

  test("one message is singular", () => {
    expect(compactionLabel(divider({ foldedMessages: 1 }))).toContain(
      "1 Message FOLDED",
    );
  });

  test("a half-reported delta still prints", () => {
    // Only one side rounding to nothing is still a fact worth stating — a fold that
    // replaced measurable text with an estimate under a thousand tokens is the fold
    // working, not a fold with nothing to say.
    expect(compactionLabel(divider({ tokensAfter: 0 }))).toContain("~62k → ~0");
  });
});

describe("approxTokens reports magnitude, not digits", () => {
  test("it scales at each threshold", () => {
    expect(approxTokens(0)).toBe("~0");
    expect(approxTokens(999)).toBe("~999");
    expect(approxTokens(1_000)).toBe("~1k");
    expect(approxTokens(62_431)).toBe("~62k");
    expect(approxTokens(1_500_000)).toBe("~1.5M");
  });
});
