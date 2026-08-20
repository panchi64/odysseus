import { type JSX } from "solid-js";
import { RecentsRail } from "~/features/chat/components/RecentsRail";

interface RailSlot {
  match: string;
  render: () => JSX.Element;
}

/**
 * Feature-owned panels the rail mounts above the area sections — the one place
 * the shell hosts feature content. It decides *where* and nothing else.
 *
 * Most areas need no entry: their options are pages, which are already rows in
 * the nav model. A slot is for live content a static row can't express.
 */
export const RAIL_SLOTS: RailSlot[] = [
  { match: "/chat", render: () => <RecentsRail /> },
];

export function railSlotFor(pathname: string): RailSlot | undefined {
  let best: RailSlot | undefined;
  let bestLen = -1;
  for (const slot of RAIL_SLOTS) {
    const hit =
      pathname === slot.match || pathname.startsWith(`${slot.match}/`);
    if (hit && slot.match.length > bestLen) {
      best = slot;
      bestLen = slot.match.length;
    }
  }
  return best;
}
