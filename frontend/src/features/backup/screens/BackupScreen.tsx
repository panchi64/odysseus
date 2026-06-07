import {
  createSignal,
  For,
  onCleanup,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import {
  Button,
  Checkbox,
  Divider,
  EmptyState,
  ErrorState,
  InstrumentBand,
  ListRow,
  LoadingText,
  Modal,
  PageHeader,
  Panel,
  ProgressBar,
  Row,
  Stack,
  StatusFlag,
  Text,
  confirm,
  toast,
} from "~/ui";
import { bytes, timestamp, relativeTime } from "~/lib/format";
import { useLastBackup } from "../data";
import type { BackupInclude } from "../model";

const ALL_INCLUDES: BackupInclude[] = [
  "memories",
  "skills",
  "presets",
  "settings",
  "preferences",
];

export function BackupScreen(): JSX.Element {
  const lastBackup = useLastBackup();

  // Export state
  const [includes, setIncludes] = createSignal<BackupInclude[]>([
    ...ALL_INCLUDES,
  ]);
  const [exportProgress, setExportProgress] = createSignal<number | null>(null);
  const [exportDone, setExportDone] = createSignal(false);
  const [exportError, setExportError] = createSignal<string | null>(null);
  const [exportBlob, setExportBlob] = createSignal<Blob | null>(null);
  let exportInterval: ReturnType<typeof setInterval> | null = null;

  // Import state
  const [importFile, setImportFile] = createSignal<File | null>(null);
  const [importOpen, setImportOpen] = createSignal(false);
  const [importProgress, setImportProgress] = createSignal<number | null>(null);
  const [importDone, setImportDone] = createSignal(false);
  const [importError, setImportError] = createSignal<string | null>(null);
  let importInterval: ReturnType<typeof setInterval> | null = null;

  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => {
    timers.forEach(clearTimeout);
    if (exportInterval) clearInterval(exportInterval);
    if (importInterval) clearInterval(importInterval);
  });

  function toggleInclude(item: BackupInclude) {
    setIncludes((s) =>
      s.includes(item) ? s.filter((x) => x !== item) : [...s, item],
    );
  }

  async function handleExportClick() {
    if (includes().length === 0) return;

    const selectedItems = includes();
    const backupData = lastBackup();
    const itemSummary = selectedItems
      .map((key) => {
        const found = backupData?.items.find((i) => i.name === key);
        return `${key.toUpperCase()}: ${found ? `${found.count} items` : "all items"}`;
      })
      .join(", ");

    const ok = await confirm({
      title: "CONFIRM EXPORT",
      detail: `Selected: ${itemSummary}. This will generate a JSON archive of your workspace data.`,
      confirmLabel: "CONFIRM EXPORT",
      cancelLabel: "CANCEL",
    });
    if (!ok) return;

    runExport();
  }

  function runExport() {
    setExportDone(false);
    setExportError(null);
    setExportBlob(null);
    setExportProgress(0);
    const steps = includes().length;
    let step = 0;
    exportInterval = setInterval(() => {
      step++;
      setExportProgress(Math.round((step / steps) * 100));
      if (step >= steps) {
        if (exportInterval) clearInterval(exportInterval);
        exportInterval = null;
        const t = setTimeout(() => {
          setExportProgress(null);
          setExportDone(true);
          // Build mock blob for download
          const mockPayload = {
            createdAt: new Date().toISOString(),
            includes: includes(),
            data: Object.fromEntries(
              includes().map((key) => [key, { exported: true }]),
            ),
          };
          setExportBlob(
            new Blob([JSON.stringify(mockPayload, null, 2)], {
              type: "application/json",
            }),
          );
          toast.success("Export complete — ready to download.");
        }, 400);
        timers.push(t);
      }
    }, 350);
  }

  function cancelExport() {
    if (exportInterval) {
      clearInterval(exportInterval);
      exportInterval = null;
    }
    setExportProgress(null);
    setExportDone(false);
    setExportError(null);
    setExportBlob(null);
    toast.info("Export cancelled.");
  }

  function retryExport() {
    setExportError(null);
    runExport();
  }

  function downloadBackup() {
    const blob = exportBlob();
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "odysseus-backup.json";
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Download started.");
  }

  function confirmImport() {
    setImportOpen(false);
    setImportDone(false);
    setImportError(null);
    setImportProgress(0);
    let pct = 0;
    importInterval = setInterval(() => {
      pct += 10;
      setImportProgress(pct);
      if (pct >= 100) {
        if (importInterval) clearInterval(importInterval);
        importInterval = null;
        const t = setTimeout(() => {
          setImportProgress(null);
          setImportDone(true);
          setImportFile(null);
        }, 400);
        timers.push(t);
      }
    }, 200);
  }

  function cancelImport() {
    if (importInterval) {
      clearInterval(importInterval);
      importInterval = null;
    }
    setImportProgress(null);
    setImportDone(false);
    setImportError(null);
    toast.info("Import cancelled.");
  }

  function retryImport() {
    setImportError(null);
    confirmImport();
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="BACKUP / RESTORE"
        subtitle="Export workspace data or restore from a previous backup archive."
        assetId="ODY-ADM-06.0 EDITION 01"
        actions={
          <Suspense fallback={<LoadingText />}>
            <Show when={lastBackup()}>
              {(b) => (
                <StatusFlag status="nominal" dot>
                  {`LAST: ${relativeTime(b().createdAt)}`}
                </StatusFlag>
              )}
            </Show>
          </Suspense>
        }
      />

      {/* ── LAST BACKUP BAND ─────────────────────────────────── */}
      <Suspense fallback={<LoadingText />}>
        <Show
          when={lastBackup()}
          fallback={
            <EmptyState
              message="NO BACKUPS YET"
              hint="Run your first export to get started. Select the categories below and click EXPORT BACKUP."
            />
          }
        >
          {(b) => (
            <InstrumentBand
              items={[
                { label: "LAST BACKUP", value: timestamp(b().createdAt) },
                ...b().items.map((item) => ({
                  label: item.name.toUpperCase(),
                  value: String(item.count),
                })),
              ]}
            />
          )}
        </Show>
      </Suspense>

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* ── EXPORT ───────────────────────────────────────── */}
        <Panel label="EXPORT">
          <Stack gap={4}>
            <Text variant="body" tone="dim">
              Select what to include in the backup archive. Output is a JSON
              file.
            </Text>
            <Stack gap={2}>
              <Text variant="label" tone="dim">
                INCLUDE
              </Text>
              <For each={ALL_INCLUDES}>
                {(item) => (
                  <Checkbox
                    label={item.toUpperCase()}
                    checked={includes().includes(item)}
                    onChange={() => toggleInclude(item)}
                  />
                )}
              </For>
            </Stack>
            <Divider />
            <Show when={exportProgress() !== null}>
              <Stack gap={2}>
                <ProgressBar
                  label="EXPORTING…"
                  value={exportProgress()!}
                  tone="nominal"
                  showValue
                />
                <Button variant="ghost" size="sm" onClick={cancelExport}>
                  CANCEL
                </Button>
              </Stack>
            </Show>
            <Show when={exportError()}>
              {(err) => (
                <ErrorState
                  message={err()}
                  hint="Check your connection and try again."
                  onRetry={retryExport}
                  retryLabel="RETRY EXPORT"
                />
              )}
            </Show>
            <Show when={exportDone()}>
              <ListRow
                label="odysseus-backup.json"
                leading="download"
                flush
                right={
                  <Row gap={2} align="center">
                    <StatusFlag status="nominal" dot>
                      READY
                    </StatusFlag>
                    <Button
                      variant="ghost"
                      size="sm"
                      leading="download"
                      onClick={downloadBackup}
                    >
                      DOWNLOAD
                    </Button>
                  </Row>
                }
              />
            </Show>
            <Button
              variant="primary"
              leading="download"
              onClick={handleExportClick}
              disabled={
                includes().length === 0 ||
                exportProgress() !== null ||
                exportError() !== null
              }
            >
              EXPORT BACKUP
            </Button>
          </Stack>
        </Panel>

        {/* ── IMPORT ───────────────────────────────────────── */}
        <Panel label="IMPORT / RESTORE">
          <Stack gap={4}>
            <Text variant="body" tone="dim">
              Restore from a previously exported backup archive. Existing data
              will be overwritten for selected sections.
            </Text>

            {/* Drop zone */}
            <div class="flex min-h-24 flex-col items-center justify-center gap-2 border border-dashed border-line bg-raised p-4">
              <Show
                when={importFile()}
                fallback={
                  <Stack gap={2} class="items-center">
                    <Text variant="label" tone="dim">
                      DROP BACKUP FILE HERE
                    </Text>
                    <Text variant="micro" tone="dim">
                      or select below
                    </Text>
                  </Stack>
                }
              >
                {(f) => (
                  <Stack gap={1} class="items-center">
                    <Text variant="label" tone="bright">
                      {f().name}
                    </Text>
                    <Text variant="micro" tone="dim">
                      {bytes(f().size)}
                    </Text>
                  </Stack>
                )}
              </Show>
            </div>

            <label class="flex flex-col gap-1">
              <Text variant="label" tone="dim">
                SELECT FILE
              </Text>
              <input
                type="file"
                accept=".json"
                class="block w-full cursor-pointer border border-line bg-surface px-2 py-1.5 text-label font-mono text-bright file:mr-3 file:border-0 file:bg-raised file:px-2 file:py-1 file:text-label file:font-mono file:text-dim"
                onChange={(e) =>
                  setImportFile(e.currentTarget.files?.[0] ?? null)
                }
              />
            </label>

            <Show when={importProgress() !== null}>
              <Stack gap={2}>
                <ProgressBar
                  label="RESTORING…"
                  value={importProgress()!}
                  tone="info"
                  showValue
                />
                <Button variant="ghost" size="sm" onClick={cancelImport}>
                  CANCEL
                </Button>
              </Stack>
            </Show>
            <Show when={importError()}>
              {(err) => (
                <ErrorState
                  message={err()}
                  hint="Ensure the file is a valid Odysseus backup archive."
                  onRetry={retryImport}
                  retryLabel="RETRY IMPORT"
                />
              )}
            </Show>
            <Show when={importDone()}>
              <Stack gap={3}>
                <StatusFlag status="nominal" dot>
                  RESTORE COMPLETE
                </StatusFlag>
                <Button
                  variant="primary"
                  onClick={() => window.location.reload()}
                >
                  CLOSE &amp; REFRESH
                </Button>
              </Stack>
            </Show>

            <Button
              variant="default"
              leading="upload"
              onClick={() => setImportOpen(true)}
              disabled={
                !importFile() ||
                importProgress() !== null ||
                importDone() ||
                importError() !== null
              }
            >
              IMPORT BACKUP
            </Button>
          </Stack>
        </Panel>
      </div>

      {/* ── IMPORT CONFIRM MODAL ─────────────────────────────── */}
      <Modal
        open={importOpen()}
        onClose={() => setImportOpen(false)}
        title="CONFIRM RESTORE"
        footer={
          <>
            <Button variant="ghost" onClick={() => setImportOpen(false)}>
              CANCEL
            </Button>
            <Button variant="danger" onClick={confirmImport}>
              OVERWRITE &amp; RESTORE
            </Button>
          </>
        }
      >
        <Stack gap={3}>
          <StatusFlag status="warn" dot>
            DESTRUCTIVE OPERATION
          </StatusFlag>
          <Text variant="body" tone="default">
            Restoring from{" "}
            <Text as="span" tone="bright">
              {importFile()?.name ?? "backup"}
            </Text>{" "}
            will overwrite existing data for all sections included in the
            archive.
          </Text>
          <Text variant="micro" tone="dim">
            This cannot be undone. Export a current backup before proceeding if
            you want to preserve existing data.
          </Text>
        </Stack>
      </Modal>
    </Stack>
  );
}
