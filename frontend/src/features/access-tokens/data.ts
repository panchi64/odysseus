import { createResource, createSignal, type Resource } from "solid-js";
import { api } from "~/lib/api";
import type { AccessToken, IssuedAccessToken, TokenScope } from "./model";

/** The only place this feature talks to the backend (`/tokens`). Distinct from
 *  `features/tokens/data.ts`, which talks to `/credentials` — outbound service keys. */

interface TokenDto {
  id: string;
  label: string;
  prefix: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

interface IssuedTokenDto extends TokenDto {
  token: string;
}

interface ScopeDto {
  id: string;
  label: string;
  description: string;
}

/** The single snake_case→camel mapper for a token row. */
function toToken(dto: TokenDto): AccessToken {
  return {
    id: dto.id,
    label: dto.label,
    prefix: dto.prefix,
    scopes: dto.scopes,
    createdAt: dto.created_at,
    lastUsedAt: dto.last_used_at,
    revokedAt: dto.revoked_at,
  };
}

const [tick, setTick] = createSignal(0);

export function useAccessTokens(): Resource<AccessToken[]> {
  const [data] = createResource(tick, async () =>
    (await api.get<TokenDto[]>("/tokens")).map(toToken),
  );
  return data;
}

/** The scope catalog is the backend's declaration of what is grantable — fetched, not
 *  hardcoded here, so a new capability appears without a frontend change. */
export function useTokenScopes(): Resource<TokenScope[]> {
  const [data] = createResource(async () =>
    api.get<ScopeDto[]>("/tokens/scopes"),
  );
  return data;
}

/** Mint a token. The plaintext in the response is the only copy that will ever exist. */
export async function issueAccessToken(
  label: string,
  scopes: string[],
): Promise<IssuedAccessToken> {
  const dto = await api.post<IssuedTokenDto>("/tokens", { label, scopes });
  setTick((n) => n + 1);
  return { ...toToken(dto), token: dto.token };
}

export async function revokeAccessToken(id: string): Promise<void> {
  await api.del(`/tokens/${id}`);
  setTick((n) => n + 1);
}
