import {
  createEffect,
  createSignal,
  For,
  onCleanup,
  Show,
  Suspense,
  type JSX,
} from "solid-js";
import { createStore, produce, reconcile } from "solid-js/store";
import {
  Button,
  EmptyState,
  InstrumentBand,
  Input,
  ListRow,
  LoadingText,
  PageHeader,
  Panel,
  Row,
  Select,
  Stack,
  StatusFlag,
  Text,
} from "~/ui";
import { bytes, num, pct, relativeTime } from "~/lib/format";
import {
  useSpeechCacheStats,
  useCachedAudio,
  ttsProviders,
  ttsVoices,
  sttProviders,
  sttLanguages,
} from "../data";
import type { CachedAudio } from "../model";

function formatDuration(ms: number): string {
  const s = ms / 1000;
  return `${num(s, 1)}S`;
}

export function SpeechScreen(): JSX.Element {
  const cacheStats = useSpeechCacheStats();
  const cachedAudioResource = useCachedAudio();

  // TTS state
  const [ttsProvider, setTtsProvider] = createSignal("kokoro");
  const [ttsVoice, setTtsVoice] = createSignal("af_heart");
  const [sampleText, setSampleText] = createSignal(
    "The vector index migration will complete in under two minutes.",
  );
  const [synthesizing, setSynthesizing] = createSignal(false);
  const [cachedAudio, setCachedAudio] = createStore<CachedAudio[]>([]);

  // Seed once from the (async) resource
  let seeded = false;
  createEffect(() => {
    const data = cachedAudioResource();
    if (!seeded && data) {
      seeded = true;
      setCachedAudio(reconcile(data.slice()));
    }
  });
  const [playingId, setPlayingId] = createSignal<string | null>(null);
  const timers: ReturnType<typeof setTimeout>[] = [];

  // STT state
  const [sttProvider, setSttProvider] = createSignal("whisper");
  const [sttLanguage, setSttLanguage] = createSignal("en");
  const [recording, setRecording] = createSignal(false);
  const [sttResult, setSttResult] = createSignal<string | null>(null);

  onCleanup(() => timers.forEach(clearTimeout));

  const voiceOptions = () => ttsVoices[ttsProvider()] ?? [];

  function synthesize() {
    if (!sampleText().trim() || synthesizing()) return;
    setSynthesizing(true);
    timers.push(
      setTimeout(() => {
        const newEntry: CachedAudio = {
          id: `aud-${Date.now()}`,
          text: sampleText(),
          durationMs: Math.floor(
            sampleText().split(" ").length * 280 + Math.random() * 500,
          ),
          provider: ttsProvider(),
          voice: ttsVoice(),
          createdAt: new Date().toISOString(),
        };
        setCachedAudio(produce((s) => s.unshift(newEntry)));
        setSynthesizing(false);
      }, 1200),
    );
  }

  function playAudio(id: string, durationMs: number) {
    if (playingId() === id) {
      setPlayingId(null);
      return;
    }
    setPlayingId(id);
    timers.push(
      setTimeout(() => {
        setPlayingId((cur) => (cur === id ? null : cur));
      }, durationMs),
    );
  }

  function startRecording() {
    if (recording()) return;
    setRecording(true);
    setSttResult(null);
    timers.push(
      setTimeout(() => {
        setRecording(false);
        setSttResult(
          "The vector index migration plan uses a shadow collection for zero-downtime re-embedding.",
        );
      }, 2500),
    );
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="SPEECH"
        subtitle="Text-to-speech synthesis and speech-to-text transcription."
        assetId="SYS-SPH-06.1"
        actions={<StatusFlag status="nominal">KOKORO LIVE</StatusFlag>}
      />

      <Suspense fallback={<LoadingText label="LOADING STATS" />}>
        <Show when={cacheStats()}>
          {(s) => (
            <InstrumentBand
              items={[
                { label: "CACHED ENTRIES", value: String(s().totalEntries) },
                { label: "CACHE SIZE", value: bytes(s().totalBytes) },
                { label: "HIT RATE", value: pct(s().hitRate * 100) },
                { label: "TTS PROVIDER", value: ttsProvider().toUpperCase() },
                { label: "STT PROVIDER", value: sttProvider().toUpperCase() },
              ]}
            />
          )}
        </Show>
      </Suspense>

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* TTS Panel */}
        <Panel label="TEXT-TO-SPEECH">
          <Stack gap={4}>
            <div class="grid grid-cols-2 gap-3">
              <Select
                label="PROVIDER"
                options={ttsProviders}
                value={ttsProvider()}
                onChange={(value) => {
                  setTtsProvider(value);
                  const voices = ttsVoices[value];
                  if (voices?.length) setTtsVoice(voices[0].value);
                }}
              />
              <Select
                label="VOICE"
                options={voiceOptions()}
                value={ttsVoice()}
                onChange={(value) => setTtsVoice(value)}
              />
            </div>
            <Input
              label="SAMPLE TEXT"
              value={sampleText()}
              onInput={(e) => setSampleText(e.currentTarget.value)}
              placeholder="Enter text to synthesize…"
            />
            <Button
              variant="primary"
              leading="play"
              onClick={synthesize}
              disabled={synthesizing() || !sampleText().trim()}
              block
            >
              {synthesizing() ? "SYNTHESIZING…" : "SYNTHESIZE"}
            </Button>
          </Stack>
        </Panel>

        {/* STT Panel */}
        <Panel label="SPEECH-TO-TEXT">
          <Stack gap={4}>
            <div class="grid grid-cols-2 gap-3">
              <Select
                label="PROVIDER"
                options={sttProviders}
                value={sttProvider()}
                onChange={(value) => setSttProvider(value)}
              />
              <Select
                label="LANGUAGE"
                options={sttLanguages}
                value={sttLanguage()}
                onChange={(value) => setSttLanguage(value)}
              />
            </div>
            <Button
              variant={recording() ? "danger" : "default"}
              leading={recording() ? "stop" : "mic"}
              onClick={startRecording}
              disabled={recording()}
              block
            >
              {recording() ? "RECORDING…" : "RECORD"}
            </Button>
            <Show when={recording()}>
              <StatusFlag status="alert" dot>
                CAPTURING AUDIO
              </StatusFlag>
            </Show>
            <Show when={sttResult()}>
              <Panel label="TRANSCRIPT" state="active">
                <Text variant="body" tone="bright">
                  {sttResult()}
                </Text>
              </Panel>
            </Show>
          </Stack>
        </Panel>
      </div>

      {/* Audio cache */}
      <Panel
        label="AUDIO CACHE"
        meta={
          <Text variant="micro" tone="dim">
            {cachedAudio.length} ENTRIES
          </Text>
        }
        flush
      >
        <Show
          when={cachedAudio.length}
          fallback={
            <EmptyState
              icon="mic"
              message="NO CACHED AUDIO"
              hint="Synthesize audio to populate the cache."
            />
          }
        >
          <For each={cachedAudio}>
            {(audio) => (
              <ListRow
                label={
                  audio.text.length > 60
                    ? audio.text.slice(0, 60) + "…"
                    : audio.text
                }
                leading="mic"
                right={
                  <Row gap={2} align="center">
                    <Text variant="micro" tone="dim">
                      {audio.voice}
                    </Text>
                    <Text variant="micro" tone="dim">
                      {formatDuration(audio.durationMs)}
                    </Text>
                    <Text variant="micro" tone="dim">
                      {relativeTime(audio.createdAt)}
                    </Text>
                    <Button
                      size="sm"
                      variant={playingId() === audio.id ? "danger" : "default"}
                      leading={playingId() === audio.id ? "pause" : "play"}
                      onClick={() => playAudio(audio.id, audio.durationMs)}
                    >
                      {playingId() === audio.id ? "STOP" : "PLAY"}
                    </Button>
                  </Row>
                }
              />
            )}
          </For>
        </Show>
      </Panel>
    </Stack>
  );
}
