/**
 * What the open thread is running on, as one fact derived once.
 *
 * This used to be answered per turn, above every assistant message. That stamped the
 * same name down the whole transcript and still didn't answer the question the operator
 * actually has — *what is this thread on?* — because a turn can only speak for itself.
 * The header asks once, so the derivation lives here rather than in the row that
 * happened to render it.
 */

import { selectedModelLabel } from "~/lib/stores/models";
import type { ChatMessage } from "./model";

/**
 * The model this conversation is running on, or null when there is nothing honest to
 * name.
 *
 * **The most recent assistant turn that recorded one.** A turn adopts the backend's
 * model once its run settles, so scanning back for the newest one is what makes this
 * track a mid-thread model switch rather than reporting whatever the thread opened on.
 *
 * **A turn in flight, and a thread with no answers yet, fall back to the live binding.**
 * Neither is a guess. An unanswered thread genuinely *will* run on the current pick, and
 * a streaming turn hasn't adopted the backend's name yet — it is *what is running*, the
 * same fact from the same source arriving a beat later. Crucially the in-flight case
 * outranks an older recorded model: if the operator switched models and sent, the
 * previous turn's name is the one thing on screen that is now wrong.
 *
 * **A settled thread never falls back.** An old turn whose model the backend didn't
 * record was not necessarily run on today's selection, and naming it would be a guess
 * wearing the same type as a fact.
 *
 * **Null, never a placeholder.** The per-turn version ended on the literal `LLM` because
 * a metadata row with a hole in it reads as broken. A header subtitle has no such
 * problem: it simply isn't drawn, which is the truthful rendering of "nothing is bound".
 */
export function conversationModel(messages: ChatMessage[]): string | null {
  const live = () => selectedModelLabel() || null;

  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role !== "assistant") continue;
    if (m.model) return m.model;
    // The newest assistant turn, still streaming and not yet stamped: the binding is
    // the truthful answer, and looking further back would name the model it replaced.
    if (m.streaming) return live();
    return null;
  }
  return live();
}
