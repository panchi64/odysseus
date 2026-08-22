import { type JSX } from "solid-js";
import { Disclosure, PageHeader, Stack, toast } from "~/ui";
import { isApiError } from "~/lib/api";
import {
  decodeModelValue,
  effectiveSelection,
  effectiveValue,
  encodeModelValue,
  modelPickerGroups,
  type ModelEndpoint,
} from "~/lib/stores/models";
import {
  setRoleBinding,
  setSelectedModel,
  useEndpoints,
  useRoles,
} from "../data";
import { EmbeddingRoleControls } from "../components/EmbeddingRoleControls";
import { EndpointsSection } from "../components/EndpointsSection";
import { FallbackChainsSection } from "../components/FallbackChainsSection";
import { ModelRoleCard } from "../components/ModelRoleCard";

/** The one home for "which model does what".
 *
 *  Three jobs, named the way an operator thinks about them rather than by the
 *  backend's role ids: the model that answers you (`main`), the cheap one that
 *  does background work (`utility`), and the one that powers recall
 *  (`embedding`). Each card offers a single combined picker over the SAME
 *  discovery groups the top-bar picker reads, so the two surfaces cannot
 *  disagree about what's selected, and each writes through the store's existing
 *  role actions — no role call is issued here.
 *
 *  Endpoint plumbing (which providers exist) and fallback ordering (where a
 *  request goes when the primary is down) are real but rare, so they sit behind
 *  ADVANCED instead of competing with the choice most people came to make. */
export function ModelsScreen(): JSX.Element {
  const endpoints = useEndpoints();
  const roles = useRoles();

  const endpointById = (id: string | undefined): ModelEndpoint | undefined =>
    id ? (endpoints.latest ?? []).find((e) => e.id === id) : undefined;

  /* ── CHAT ──────────────────────────────────────────────────────────────────
     Read and written through exactly the accessors the top-bar picker uses, so
     the two controls are the same control wearing different chrome. */
  const chatEndpoint = () => endpointById(effectiveSelection()?.endpointId);
  const pickChat = async (value: string) => {
    const sel = decodeModelValue(value);
    if (!sel) return;
    try {
      await setSelectedModel(sel);
      toast.success(`Chat model set to ${sel.model}.`);
    } catch (e) {
      toast.error(isApiError(e) ? e.detail : "Unable to set the chat model.");
    }
  };

  /* ── The bound roles ───────────────────────────────────────────────────────
     A role's pick as one picker value: the pinned model if there is one, else
     the head endpoint's own default — which is what the backend resolves to, so
     the picker shows the model that actually runs rather than an
     "endpoint default" abstraction. Picking always pins explicitly. */
  const roleEndpoint = (role: string): ModelEndpoint | undefined =>
    endpointById(roles()?.[role]?.endpointIds?.[0]);
  /** The role's chain with `head` promoted to primary and every other member kept
   *  behind it. Picking a *model* must not silently change where a request goes when
   *  the primary is down — the mirror of the invariant `FallbackChainsSection` holds
   *  (reordering preserves the pinned model). Writing `[head]` outright would drop the
   *  fallbacks configured under ADVANCED with nothing on screen saying so. */
  const chainHeadedBy = (role: string, head: string): string[] => [
    head,
    ...(roles()?.[role]?.endpointIds ?? []).filter((id) => id !== head),
  ];
  const roleValue = (role: string): string => {
    const ep = roleEndpoint(role);
    if (!ep) return "";
    const model = roles()?.[role]?.model ?? ep.model;
    return model ? encodeModelValue({ endpointId: ep.id, model }) : "";
  };

  /* An unbound `utility` is not a broken state: the backend degrades background
     work onto the chat model. So "same as chat model" is spelled as the empty
     binding it already is, rather than as a fourth thing to configure. */
  const SAME_AS_CHAT = "";
  const backgroundGroups = () => [
    {
      label: "DEFAULT",
      options: [{ value: SAME_AS_CHAT, label: "SAME AS CHAT MODEL" }],
    },
    ...modelPickerGroups(),
  ];
  const pickBackground = async (value: string) => {
    const sel = value === SAME_AS_CHAT ? null : decodeModelValue(value);
    if (value !== SAME_AS_CHAT && !sel) return;
    try {
      await setRoleBinding(
        "utility",
        sel ? chainHeadedBy("utility", sel.endpointId) : [],
        sel?.model ?? null,
      );
      toast.success(
        sel
          ? `Background model set to ${sel.model}.`
          : "Background work now uses the chat model.",
      );
    } catch (e) {
      toast.error(
        isApiError(e) ? e.detail : "Unable to set the background model.",
      );
    }
  };

  const pickEmbedding = async (value: string) => {
    const sel = decodeModelValue(value);
    if (!sel) return;
    try {
      const reindexStarted = await setRoleBinding(
        "embedding",
        chainHeadedBy("embedding", sel.endpointId),
        sel.model,
      );
      if (reindexStarted)
        toast.info("Re-embedding memories and chats for the new model…");
      else toast.success(`Search & memory model set to ${sel.model}.`);
    } catch (e) {
      toast.error(
        isApiError(e) ? e.detail : "Unable to set the search & memory model.",
      );
    }
  };

  return (
    <Stack gap={6}>
      <PageHeader
        title="MODELS"
        subtitle="Which model does what. Set it here once — every surface follows."
        assetId="ODY-MDL-01.0"
      />

      <ModelRoleCard
        label="CHAT MODEL"
        description="Answers you in chat, research, and tasks."
        groups={modelPickerGroups()}
        value={effectiveValue()}
        onChange={(v) => void pickChat(v)}
        placeholder="NO MODEL"
        endpoint={chatEndpoint()}
      />

      <ModelRoleCard
        label="BACKGROUND MODEL"
        description="Titles, summaries, verification. A cheaper model is usually the right call."
        groups={backgroundGroups()}
        value={roleValue("utility")}
        onChange={(v) => void pickBackground(v)}
        placeholder="SAME AS CHAT MODEL"
        endpoint={roleEndpoint("utility")}
      />

      <ModelRoleCard
        label="SEARCH & MEMORY MODEL"
        description="Powers recall across memories and chats. Changing this re-indexes everything."
        groups={modelPickerGroups()}
        value={roleValue("embedding")}
        onChange={(v) => void pickEmbedding(v)}
        placeholder="NOT SET — RECALL IS KEYWORD-ONLY"
        endpoint={roleEndpoint("embedding")}
      >
        <EmbeddingRoleControls
          bound={roleEndpoint("embedding") !== undefined}
        />
      </ModelRoleCard>

      <Disclosure label="ADVANCED">
        <Stack gap={6} class="pt-3">
          <EndpointsSection />
          <FallbackChainsSection />
        </Stack>
      </Disclosure>
    </Stack>
  );
}
