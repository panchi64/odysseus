import { api, isApiError } from "~/lib/api";
// The direct module path, not the `~/ui` barrel: Markdown.tsx is *inside* that
// barrel and imports this, so going back through it would close an import cycle
// for the sake of one function.
import { toast } from "~/ui/components/Toast";

/**
 * Open a file named in an answer, on the machine the backend is running on.
 *
 * The browser cannot do this — `file://` navigation is blocked from a page, and
 * it would show the file in a tab rather than in the operator's editor — so the
 * click becomes a REST call to the process that *is* on their machine, and the
 * OS picks the application. See `backend/services/host_open.py`.
 *
 * Nothing is shown when it works: the editor coming forward is the feedback, and
 * a toast confirming what the operator just watched happen is noise. A failure
 * always speaks, because the alternative is a control that silently does nothing
 * — and the two ways this fails are both worth reading. The backend refuses a
 * path outside the operator's own projects (the fence, since the path came from
 * model-written prose), and a host with no opener says so in a sentence.
 */
export async function openHostPath(path: string): Promise<void> {
  const wanted = path.trim();
  if (!wanted) return;
  try {
    await api.post<{ path: string }>("/host/open", { path: wanted });
  } catch (err) {
    toast.error((isApiError(err) && err.detail) || `Couldn't open ${wanted}`);
  }
}
