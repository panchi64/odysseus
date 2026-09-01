/**
 * The chat preferences on the wire, and the two mappings to and from them.
 *
 * Split out of `data.ts` for one reason: this is pure data → data, and `data.ts` is a
 * module that reaches the network and the models store the moment it is imported. Only
 * one of those two things can be pinned by a test in a runtime with no DOM, and it is
 * this one — which happens to be the half where a mistake is silent.
 *
 * **The silent mistake is the falsy value.** A PUT here carries only the keys the
 * caller touched, and "touched" has to be an `!== undefined` test rather than a
 * truthiness one, because two of these settings have a meaningful falsy value: keeping
 * **0** exchanges verbatim past a fold is a real choice (let the summary stand for
 * everything), and a **null** wall clock is the value that removes the bound. Under a
 * truthiness test both are dropped on the way out, with no error and no sign — and only
 * for the operators who chose them.
 */

import type { ChatSettings } from "./model";

export interface ChatSettingsDTO {
  auto_compact_enabled: boolean;
  auto_compact_threshold: number;
  auto_compact_keep_turns: number;
  context_warn_threshold: number;
  context_alert_threshold: number;
  agent_request_limit: number;
  inactivity_timeout_s: number;
  wall_clock_timeout_s: number | null;
}

/** The single snake_case→camel mapper for the stored chat preferences. */
export function toChatSettings(dto: ChatSettingsDTO): ChatSettings {
  return {
    autoCompactEnabled: dto.auto_compact_enabled,
    autoCompactThreshold: dto.auto_compact_threshold,
    autoCompactKeepTurns: dto.auto_compact_keep_turns,
    contextWarnThreshold: dto.context_warn_threshold,
    contextAlertThreshold: dto.context_alert_threshold,
    agentRequestLimit: dto.agent_request_limit,
    inactivityTimeoutS: dto.inactivity_timeout_s,
    wallClockTimeoutS: dto.wall_clock_timeout_s,
  };
}

/** Map a camelCase patch to the backend's snake_case body (an omitted field is left
 *  unchanged on the backend, so only present keys are written). */
export function toChatSettingsBody(
  patch: Partial<ChatSettings>,
): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (patch.autoCompactEnabled !== undefined)
    body.auto_compact_enabled = patch.autoCompactEnabled;
  if (patch.autoCompactThreshold !== undefined)
    body.auto_compact_threshold = patch.autoCompactThreshold;
  if (patch.autoCompactKeepTurns !== undefined)
    body.auto_compact_keep_turns = patch.autoCompactKeepTurns;
  if (patch.contextWarnThreshold !== undefined)
    body.context_warn_threshold = patch.contextWarnThreshold;
  if (patch.contextAlertThreshold !== undefined)
    body.context_alert_threshold = patch.contextAlertThreshold;
  if (patch.agentRequestLimit !== undefined)
    body.agent_request_limit = patch.agentRequestLimit;
  if (patch.inactivityTimeoutS !== undefined)
    body.inactivity_timeout_s = patch.inactivityTimeoutS;
  if (patch.wallClockTimeoutS !== undefined)
    body.wall_clock_timeout_s = patch.wallClockTimeoutS;
  return body;
}
