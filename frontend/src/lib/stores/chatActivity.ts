/** Global chat-activity echoes for the main chat room.
 *
 *  `chatBusy` — true while a turn is streaming. The app shell's nav rail reads it to
 *  light an ambient indicator on the Chat item, so a run started before navigating away
 *  (to Email, Memory, …) is visibly still working from anywhere — returning to the room
 *  then feels continuous, not like a response that was abandoned.
 *
 *  `runErrored` — true when the room's last run ended in `run.error`; cleared when the
 *  next run starts. Feeds the platform-status derivation that tints the favicon red.
 *
 *  Both are presentation echoes only: the backend owns the run; the chat seam mirrors
 *  its state here and the consumers just render. Driven solely by the main `mainChat()`
 *  room (not the ephemeral compare panes), so they track the one conversation the
 *  operator would return to. */
import { createSignal } from "solid-js";

const [chatBusy, setChatBusy] = createSignal(false);
const [runErrored, setRunErrored] = createSignal(false);

export { chatBusy, setChatBusy, runErrored, setRunErrored };
