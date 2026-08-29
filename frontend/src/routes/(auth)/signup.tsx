import { Navigate } from "@solidjs/router";

/** Retired as a surface for the same reason as `/login` — the gate owns first-run
 *  setup now. Kept as a redirect so the path never dead-ends. */
export default function SignupRoute() {
  return <Navigate href="/" />;
}
