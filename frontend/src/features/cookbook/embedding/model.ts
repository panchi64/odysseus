/** Embedding role + reindex data contracts — the EMBEDDING tab's model-swap and
 *  index-stats surface. The catalog of servable models is `ManagedModel`
 *  (`../model`), the same list `EmbeddingServePanel` renders; this feature only
 *  adds which one is bound to the `embedding` role and the reindex job's state. */

import type { ReindexState } from "~/lib/api/models-types";

/** The `embedding` role's current binding (`GET /models/roles`). Null fields mean
 *  no embedding model has ever been bound — recall runs keyword-only. */
export interface EmbeddingRole {
  endpointId: string | null;
  model: string | null;
}

/** The re-embed job's status (`GET`/`POST /models/embedding/reindex`) — a single
 *  background job over memories + the chat index, not per-document progress. */
export interface ReindexStatus {
  state: ReindexState;
  memories: number;
  messages: number;
  detail?: string;
  completedAt?: string;
}
