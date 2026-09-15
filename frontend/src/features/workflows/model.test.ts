import { describe, expect, it } from "bun:test";
import {
  normalizeWorkflowName,
  WORKFLOW_NAME_PATTERN,
  charCount,
  workflowStatusFlag,
  workflowStatusLabel,
} from "./model";

/**
 * `normalizeWorkflowName` is a **mirror of a backend rule**, and that is the whole
 * hazard: the point of it is that the field never goes red for something the server
 * would have accepted, so the cases that matter are the ones where naive validation and
 * the real rule disagree. Those are first below.
 *
 * If `services/commands/authoring.validate_name` changes, these are what should fail.
 */
describe("normalizeWorkflowName", () => {
  it("folds spaces to hyphens rather than refusing them", () => {
    // What someone writes when they are thinking about the ritual, not the identifier.
    expect(normalizeWorkflowName("Stand Up")).toBe("stand-up");
    expect(WORKFLOW_NAME_PATTERN.test(normalizeWorkflowName("Stand Up"))).toBe(
      true,
    );
  });

  it("drops the leading slash the operator sees everywhere else", () => {
    expect(normalizeWorkflowName("/standup")).toBe("standup");
    expect(normalizeWorkflowName("//standup")).toBe("standup");
  });

  it("lowercases", () => {
    expect(normalizeWorkflowName("RELEASE-NOTES")).toBe("release-notes");
  });

  it("trims before anything else, so a stray space is not a hyphen", () => {
    expect(normalizeWorkflowName("  standup  ")).toBe("standup");
  });

  it("leaves a name that is already usable exactly alone", () => {
    // The common case, and the one that must not grow a "saves as" hint.
    expect(normalizeWorkflowName("release-notes")).toBe("release-notes");
    expect(normalizeWorkflowName("my_workflow")).toBe("my_workflow");
  });

  it("does not rescue what the rule genuinely refuses", () => {
    // Normalising is not sanitising — punctuation the backend rejects still reads as
    // invalid here, or the field would stay green through a 422.
    for (const raw of ["what?!", "-leading", "trailing-", "a.b", ""]) {
      expect(WORKFLOW_NAME_PATTERN.test(normalizeWorkflowName(raw))).toBe(
        false,
      );
    }
  });
});

describe("charCount", () => {
  it("reads as a fraction of the cap", () => {
    expect(charCount("abc", 64)).toBe("3 / 64");
  });
});

describe("workflow status", () => {
  it("says on or off, never published or draft", () => {
    // Publishing is a skill crossing into the agent's view. Nothing here crosses
    // anywhere, so borrowing that word would claim a boundary that does not exist.
    expect(workflowStatusLabel(true)).toBe("ON");
    expect(workflowStatusLabel(false)).toBe("OFF");
    expect(workflowStatusFlag(true)).toBe("nominal");
    expect(workflowStatusFlag(false)).toBe("idle");
  });
});
