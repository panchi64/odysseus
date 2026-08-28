import type { RouteSectionProps } from "@solidjs/router";
import { AuthLayout } from "~/app/AuthLayout";

/** Layout for unauthenticated surfaces (login, signup). */
export default function AuthGroupLayout(props: RouteSectionProps) {
  return <AuthLayout>{props.children}</AuthLayout>;
}
