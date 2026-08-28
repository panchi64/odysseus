import { confirm, toast } from "~/ui";
import { refreshEndpoints } from "~/lib/stores/models";
import {
  deleteModel,
  serveModel,
  stopModel,
  type ManagedModelsController,
} from "./serving";
import type { ManagedModel } from "./model";

function detail(err: unknown, fallback: string): string {
  return (err as { detail?: string })?.detail ?? fallback;
}

export interface ManagedModelActions {
  /** Launch a model's engine and register it as an endpoint (optionally binding a
   *  role). The same call serves a brand-new model or re-serves a stopped one. */
  serve: (input: Parameters<typeof serveModel>[0]) => Promise<void>;
  /** Tear an engine down; the managed record (and any role binding) survives. */
  stop: (model: ManagedModel) => Promise<void>;
  /** Stop + forget a managed model, behind a confirm gate. */
  remove: (model: ManagedModel) => Promise<void>;
}

/** The serve / stop / delete handlers shared by every managed-model surface (the
 *  LOCAL MODELS tab and the EMBEDDING tab's serve-locally affordance). Each relays
 *  the operator's intent to the backend, then refreshes the managed list *and* the
 *  shared endpoint store so a served model appears (or a deleted one vanishes) in the
 *  picker/Settings immediately.
 *
 *  Presentation only: the backend owns every lifecycle transition; these handlers
 *  just relay intent and surface the outcome as a toast. */
export function useManagedModelActions(
  controller: ManagedModelsController,
): ManagedModelActions {
  async function serve(input: Parameters<typeof serveModel>[0]): Promise<void> {
    try {
      const model = await serveModel(input);
      toast.success(`Serving ${model.hfRepo}`);
    } catch (err) {
      toast.error(detail(err, `Unable to serve ${input.repo}`));
    } finally {
      controller.refresh();
      refreshEndpoints();
    }
  }

  async function stop(model: ManagedModel): Promise<void> {
    try {
      await stopModel(model.id);
      toast.success(`Stopped ${model.hfRepo}`);
    } catch (err) {
      toast.error(detail(err, `Unable to stop ${model.hfRepo}`));
    } finally {
      controller.refresh();
      refreshEndpoints();
    }
  }

  async function remove(model: ManagedModel): Promise<void> {
    const local = model.source === "local";
    const ok = await confirm({
      title: local ? `Remove ${model.hfRepo}?` : `Delete ${model.hfRepo}?`,
      detail: local
        ? "This stops the model and removes it from this list. Your model files are left exactly where they are."
        : "This stops the model and removes its managed record. Downloaded weights stay on disk.",
      confirmLabel: local ? "REMOVE" : "DELETE",
      tone: "alert",
    });
    if (!ok) return;
    try {
      await deleteModel(model.id);
      toast.success(`Deleted ${model.hfRepo}`);
    } catch (err) {
      toast.error(detail(err, `Unable to delete ${model.hfRepo}`));
    } finally {
      controller.refresh();
      refreshEndpoints();
    }
  }

  return { serve, stop, remove };
}
