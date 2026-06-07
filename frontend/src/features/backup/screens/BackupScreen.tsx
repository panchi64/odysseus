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

  // Import state
  const [importFile, setImportFile] = createSignal<File | null>(null);
  const [importOpen, setImportOpen] = createSignal(false);
  const [importProgress, setImportProgress] = createSignal<number | null>(null);
  const [importDone, setImportDone] = createSignal(false);

  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => timers.forEach(clearTimeout));

  function toggleInclude(item: BackupInclude) {
    setIncludes((s) =>
      s.includes(item) ? s.filter((x) => x !== item) : [...s, item],
    );
  }

  function runExport() {
    setExportDone(false);
    setExportProgress(0);
    const steps = includes().length;
    let step = 0;
    const interval = setInterval(() => {
      step++;
      setExportProgress(Math.round((step / steps) * 100));
      if (step >= steps) {
        clearInterval(interval);
        const t = setTimeout(() => {
          setExportProgress(null);
          setExportDone(true);
        }, 400);
        timers.push(t);
      }
    }, 350);
    timers.push(interval);
  }

  function confirmImport() {
    setImportOpen(false);
    setImportDone(false);
    setImportProgress(0);
    let pct = 0;
    const interval = setInterval(() => {
      pct += 10;
      setImportProgress(pct);
      if (pct >= 100) {
        clearInterval(interval);
        const t = setTimeout(() => {
          setImportProgress(null);
          setImportDone(true);
          setImportFile(null);
        }, 400);
        timers.push(t);
      }
    }, 200);
    timers.push(interval);
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
        <Show when={lastBackup()}>
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
              <ProgressBar
                label="EXPORTING…"
                value={exportProgress()!}
                tone="nominal"
                showValue
              />
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
                    <Button variant="ghost" size="sm" leading="download">
                      DOWNLOAD
                    </Button>
                  </Row>
                }
              />
            </Show>
            <Button
              variant="primary"
              leading="download"
              onClick={runExport}
              disabled={includes().length === 0 || exportProgress() !== null}
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
              <ProgressBar
                label="RESTORING…"
                value={importProgress()!}
                tone="info"
                showValue
              />
            </Show>
            <Show when={importDone()}>
              <StatusFlag status="nominal" dot>
                RESTORE COMPLETE
              </StatusFlag>
            </Show>

            <Button
              variant="default"
              leading="upload"
              onClick={() => setImportOpen(true)}
              disabled={!importFile() || importProgress() !== null}
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
              OVERWRITE & RESTORE
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
