import { describe, expect, test } from "bun:test";
import { toChatSettings, toChatSettingsBody } from "./chatSettingsDto";

/**
 * The chat-settings wire mapping, in the one place it can go wrong quietly.
 *
 * A PUT here sends only the keys the caller touched, and "touched" is decided by an
 * `!== undefined` test rather than by truthiness. That distinction is invisible until a
 * setting has a meaningful falsy value — and two do: keeping **0** exchanges verbatim
 * past a fold is a real choice (summarize everything), and a `null` wall clock is the
 * value that removes the bound. Written as `if (patch.x)`, both would be dropped on the
 * floor with no error anywhere, and only for the operators who picked them.
 */

const DTO = {
  auto_compact_enabled: true,
  auto_compact_threshold: 0.8,
  auto_compact_keep_turns: 3,
  context_warn_threshold: 0.75,
  context_alert_threshold: 0.9,
  agent_request_limit: 25,
  inactivity_timeout_s: 120,
  wall_clock_timeout_s: null,
};

describe("reading the stored preferences", () => {
  test("every field arrives under its camelCase name", () => {
    expect(toChatSettings(DTO)).toEqual({
      autoCompactEnabled: true,
      autoCompactThreshold: 0.8,
      autoCompactKeepTurns: 3,
      contextWarnThreshold: 0.75,
      contextAlertThreshold: 0.9,
      agentRequestLimit: 25,
      inactivityTimeoutS: 120,
      wallClockTimeoutS: null,
    });
  });

  test("a stored 0 comes back as 0, not as a default", () => {
    expect(
      toChatSettings({ ...DTO, auto_compact_keep_turns: 0 })
        .autoCompactKeepTurns,
    ).toBe(0);
  });
});

describe("writing a patch", () => {
  test("only the touched keys are sent", () => {
    expect(toChatSettingsBody({ autoCompactKeepTurns: 3 })).toEqual({
      auto_compact_keep_turns: 3,
    });
  });

  test("keeping nothing verbatim survives the encode", () => {
    // The trap this whole file exists for.
    expect(toChatSettingsBody({ autoCompactKeepTurns: 0 })).toEqual({
      auto_compact_keep_turns: 0,
    });
  });

  test("an untouched key is absent rather than sent as a default", () => {
    // Absence is what tells the backend to leave a field alone, so a mapper that filled
    // in defaults would overwrite settings the operator never opened.
    expect(toChatSettingsBody({ autoCompactEnabled: false })).toEqual({
      auto_compact_enabled: false,
    });
  });
});
