export { ChatRoomScreen } from "./screens/ChatRoomScreen";

// The conversation engine, reused by the side-by-side compare surface: the live
// stream controller (one run via POST /chat → run SSE) and the turn renderer.
// Compare composes two of these against two models; all run lifecycle stays
// backend-owned — these are just the seam the screen renders.
export { createChatStream } from "./data";
export type { ChatStreamOptions } from "./data";
export { MessageItem } from "./components/MessageItem";
export type { ChatMessage } from "./model";
