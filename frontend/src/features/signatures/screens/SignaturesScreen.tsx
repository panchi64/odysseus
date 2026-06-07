import {
  createEffect,
  createSignal,
  For,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import {
  Button,
  EmptyState,
  InstrumentBand,
  LoadingText,
  PageHeader,
  Row,
  Stack,
  Text,
  toast,
} from "~/ui";
import { useSignatures } from "../data";
import { SignatureTile } from "../components/SignatureTile";
import { DrawSignatureModal } from "../components/DrawSignatureModal";
import type { Signature } from "../model";

let sigCounter = 0;
const nextSigId = () => `sig-live-${++sigCounter}`;

export function SignaturesScreen(): JSX.Element {
  const signaturesResource = useSignatures();
  const [signatures, setSignatures] = createSignal<Signature[]>([]);
  const [modalOpen, setModalOpen] = createSignal(false);

  let seeded = false;
  createEffect(() => {
    const data = signaturesResource();
    if (!seeded && data) {
      seeded = true;
      setSignatures(data.slice());
    }
  });

  const totalUsed = () => signatures().reduce((sum, s) => sum + s.usedCount, 0);

  function handleSave(name: string) {
    const sig: Signature = {
      id: nextSigId(),
      name,
      createdAt: new Date().toISOString(),
      usedCount: 0,
    };
    setSignatures((prev) => [...prev, sig]);
  }

  function handleDelete(id: string) {
    setSignatures((prev) => prev.filter((s) => s.id !== id));
  }

  function handleExport() {
    const sigs = signatures();
    if (sigs.length === 0) {
      toast.warn("No signatures to export.");
      return;
    }
    const json = JSON.stringify(sigs, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "odysseus-signatures.json";
    a.click();
    URL.revokeObjectURL(url);
    toast.success(
      `Exported ${sigs.length} signature${sigs.length !== 1 ? "s" : ""}.`,
    );
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="SIGNATURES"
        subtitle="Saved digital signatures for PDFs and email."
        assetId="ODY-SIG-01.0"
        actions={
          <Row gap={2}>
            <Button variant="ghost" leading="download" onClick={handleExport}>
              EXPORT ALL
            </Button>
            <Button
              variant="primary"
              leading="pen"
              onClick={() => setModalOpen(true)}
            >
              DRAW NEW
            </Button>
          </Row>
        }
      />

      <Suspense fallback={<LoadingText />}>
        <Show when={signaturesResource()}>
          <InstrumentBand
            items={[
              { label: "SAVED", value: String(signatures().length) },
              { label: "TOTAL USES", value: String(totalUsed()) },
              { label: "PDF", value: "✓", tone: "nominal" },
              { label: "EMAIL", value: "✓", tone: "nominal" },
            ]}
          />
        </Show>
      </Suspense>

      <Text
        variant="micro"
        tone="dim"
        class="border border-line px-2 py-1 w-fit"
      >
        Signatures are used for PDF document signing and email footers.
      </Text>

      <Suspense fallback={<LoadingText />}>
        <Show when={signaturesResource()}>
          <Show
            when={signatures().length > 0}
            fallback={
              <EmptyState
                icon="pen"
                message="NO SIGNATURES"
                hint="Draw a new signature to get started. Use them for PDF signing and email footers."
                action={
                  <Button
                    variant="primary"
                    leading="pen"
                    onClick={() => setModalOpen(true)}
                  >
                    DRAW NEW
                  </Button>
                }
              />
            }
          >
            <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <For each={signatures()}>
                {(sig) => (
                  <SignatureTile
                    signature={sig}
                    onDelete={() => handleDelete(sig.id)}
                  />
                )}
              </For>
            </div>
          </Show>
        </Show>
      </Suspense>

      <DrawSignatureModal
        open={modalOpen()}
        onClose={() => setModalOpen(false)}
        onSave={handleSave}
      />
    </Stack>
  );
}
