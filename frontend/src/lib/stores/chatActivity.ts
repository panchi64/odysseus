/** Global chat-activity flag — true while the main chat room has a turn streaming.
 *
 *  The app shell's nav rail reads this to light an ambient indicator on the Chat
 *  item, so a run started before navigating away (to Email, Memory, …) is visibly
 *  still working from anywhere — returning to the room then feels continuous, not
 *  like a response that was abandoned. Presentation echo only: the backend owns the
 *  run; the chat seam mirrors its `sending` state here, and the rail just renders.
 *
 *  Driven solely by the main `mainChat()` room (not the ephemeral compare panes),
 *  so it tracks the one conversation the operator would return to. */
import { createSignal } from "solid-js";

const [chatBusy, setChatBusy] = createSignal(false);

export { chatBusy, setChatBusy };
