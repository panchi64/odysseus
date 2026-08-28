import { type JSX } from "solid-js";
import { Text, type TextTone, type TextVariant } from "../primitives/Text";

export interface ExternalLinkProps {
  /** Destination URL (opens in a new tab). */
  href: string;
  /** Link text. */
  children: JSX.Element;
  /** Text tone — defaults to `info` (the link accent). */
  tone?: TextTone;
  /** Text size variant — defaults to `micro`. */
  variant?: TextVariant;
}

/** An outbound link: opens in a new tab, drops the referrer, and renders as accented
 *  text with a hover underline. The one place the design system owns the external-link
 *  affordance, so its styling and `target`/`rel` safety live in a single component. */
export function ExternalLink(props: ExternalLinkProps): JSX.Element {
  return (
    <a
      href={props.href}
      target="_blank"
      rel="noreferrer noopener"
      class="underline-offset-2 hover:underline"
    >
      <Text variant={props.variant ?? "micro"} tone={props.tone ?? "info"}>
        {props.children}
      </Text>
    </a>
  );
}
