/**
 * The two literals the chat seam agrees on with the backend.
 *
 * They live apart from the mappers because three unrelated layers need them — the cold
 * mapper, the live fold, and the terminal card — and importing any one of those from the
 * others just to reach a string would tie modules together for no other reason.
 */

/** The one approval-gated tool that runs on the real host (vs. the sandbox). Its
 *  approval + execution render as a single persistent terminal, never a generic
 *  approval card or tool card. */
export const HOST_COMMAND_TOOL = "code_run_host_command";

/** The prompt a "Continue." turn sends — the operator's way to resume a turn that a
 *  bound (inactivity/wall-clock timeout or cancel) stopped before it finished. A plain
 *  user turn on the same conversation, so the model picks up where the prior turn left
 *  off and a small "Continue." bubble appears in the transcript. */
export const CONTINUE_PROMPT = "Continue.";
