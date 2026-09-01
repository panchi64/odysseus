export { ChatRoomScreen } from "./screens/ChatRoomScreen";

// The conversation engine, reused by the side-by-side compare surface: the live
// stream controller (one run via POST /chat → run SSE) and the turn renderer.
// Compare composes two of these against two models; all run lifecycle stays
// backend-owned — these are just the seam the screen renders.
export { createChatStream } from "./data";
export type { ChatStreamOptions } from "./data";
export { MessageItem } from "./components/MessageItem";
export type { ChatMessage } from "./model";
// The View surface, so a compare pane's artifact/preview chips open the same stage the
// chat viewport does rather than being inert (`CMP-2` — previews are part of full chat
// fidelity). `ViewportPanel` is fully controlled, so the pane owns the state and mounts
// it wherever its layout allows.
export { ViewportPanel } from "./components/ViewportPanel";
export { collectViewItems, type ViewItem } from "./viewport";
// The park surface, for the same reason: a compare pane runs real turns against real
// tools, so one can stop on an approval or a question exactly as the main room's can.
// Approvals no longer render on the transcript rail, so a pane without this would show
// a parked run nothing at all — and it would wait forever.
export { ParkDock } from "./components/ParkDock";
