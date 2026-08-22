import type { ToastAction } from "~/ui";

/** Where the chat model is configured — the one home for the choice. */
export const MODELS_PAGE_HREF = "/settings/models";

/** The Cookbook can change the chat model from two places (a served local model's
 *  USE FOR CHAT, and the guided connect flow's auto-pick). Neither may do it
 *  quietly: an operator who doesn't know a role moved can't find where to move it
 *  back. Every such write acknowledges what changed and points at the page that
 *  owns it — one helper so both surfaces say it the same way. */
export function modelsPageAction(
  navigate: (href: string) => void,
): ToastAction {
  return { label: "MODELS", onClick: () => navigate(MODELS_PAGE_HREF) };
}
