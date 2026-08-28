import { Navigate } from "@solidjs/router";

/** LOCAL MODELS merged into `/settings/models`.
 *
 *  Local-versus-external was never a distinction the operator makes — a model is a
 *  model, and which host runs it is one column. The route stays as a redirect so an
 *  existing bookmark or a link in an older transcript still lands somewhere useful. */
export default function LocalModelsRoute() {
  return <Navigate href="/settings/models" />;
}
