import { Navigate } from "@solidjs/router";

/** The cookbook has no page of its own — the guided flow is the front door. */
export default function CookbookIndexRoute() {
  return <Navigate href="/models/cookbook/getstarted" />;
}
