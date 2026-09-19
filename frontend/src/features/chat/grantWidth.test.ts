import { describe, expect, test } from "bun:test";
import { tickedWidth } from "./commandScope";
import { createGrantToggle } from "./components/ConversationGrantToggle";

describe("tickedWidth", () => {
  test("a call that runs a command starts at the narrow width", () => {
    // The picker offers the wider one beside it; the narrow one has to stay the default,
    // because it is the smaller thing to say.
    expect(tickedWidth("uv run pytest")).toBe("command");
    expect(tickedWidth("cat $TARGET")).toBe("command");
  });

  test("a call that runs no command is ticked at the wider width", () => {
    // Nothing narrower exists for it to be scoped to, and the checkbox already says "this
    // tool". Recorded at the narrow width it would go on being asked about at the level
    // that reviews — the label promising a standing yes the grant does not give.
    expect(tickedWidth(undefined)).toBe("tool");
    expect(tickedWidth("")).toBe("tool");
  });
});

/** The opt-in's width, and the wire value it becomes.
 *
 *  Three scopes travel and they are not interchangeable: the narrow one records a standing
 *  yes to the act this call is, the wide one hands over the whole tool for the thread, and
 *  a mapping that slipped between them would either re-prompt an operator who asked not to
 *  be, or grant one far more than they ticked. The mapping is the only logic in a file that
 *  is otherwise a control, so it is the part worth pinning.
 */
describe("createGrantToggle", () => {
  test("no opt-in is this call only", () => {
    const grant = createGrantToggle();
    expect(grant.widthOf("k")).toBe("off");
    expect(grant.isAllowed("k")).toBe(false);
    expect(grant.scope("k", true)).toBe("once");
  });

  test("the default tick asks for the act, the wider pick for the tool", () => {
    const grant = createGrantToggle();
    grant.set("k", "command");
    expect(grant.scope("k", true)).toBe("conversation");
    grant.set("k", "tool");
    expect(grant.scope("k", true)).toBe("conversation_tool");
  });

  test("a denial carries no standing yes, whatever was ticked", () => {
    // The backend ignores scope on a no; sending one anyway would be saying something
    // untrue of the decision.
    const grant = createGrantToggle();
    grant.set("k", "tool");
    expect(grant.scope("k", false)).toBe("once");
  });

  test("each act holds its own width", () => {
    // Two commands pending in one batch are two grants, so one card's wider pick must not
    // reach the other's.
    const grant = createGrantToggle();
    grant.set("shell_run_command uv run pytest", "tool");
    expect(grant.scope("shell_run_command git commit -m", true)).toBe("once");
  });

  test("unticking clears the width rather than leaving it set", () => {
    const grant = createGrantToggle();
    grant.set("k", "tool");
    grant.set("k", "off");
    expect(grant.isAllowed("k")).toBe(false);
    expect(grant.scope("k", true)).toBe("once");
  });
});
