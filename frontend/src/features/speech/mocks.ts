import type { SpeechSettings, CachedAudio, CacheStats } from "./model";

export const mockSpeechSettings: SpeechSettings = {
  ttsProvider: "kokoro",
  ttsVoice: "af_heart",
  sttProvider: "whisper",
  sttLanguage: "en",
};

export const mockCachedAudio: CachedAudio[] = [
  {
    id: "aud-1",
    text: "Vector index migration plan: build a shadow collection, backfill, then atomically switch.",
    durationMs: 4200,
    provider: "kokoro",
    voice: "af_heart",
    createdAt: "2026-06-07T13:58:00Z",
  },
  {
    id: "aud-2",
    text: "For ~4,200 documents at roughly 80 docs/sec, the backfill itself is about 50 seconds.",
    durationMs: 3800,
    provider: "kokoro",
    voice: "af_heart",
    createdAt: "2026-06-07T12:14:00Z",
  },
];

export const mockCacheStats: CacheStats = {
  totalEntries: 48,
  totalBytes: 128_000_000,
  hitRate: 0.73,
};

export const ttsProviders = [
  { value: "kokoro", label: "Kokoro (Local)" },
  { value: "piper", label: "Piper (Local)" },
  { value: "coqui", label: "Coqui TTS (Local)" },
  { value: "elevenlabs", label: "ElevenLabs (Remote)" },
  { value: "openai", label: "OpenAI TTS (Remote)" },
];

export const ttsVoices: Record<string, { value: string; label: string }[]> = {
  kokoro: [
    { value: "af_heart", label: "af_heart (EN-US, F)" },
    { value: "af_sky", label: "af_sky (EN-US, F)" },
    { value: "am_adam", label: "am_adam (EN-US, M)" },
    { value: "bf_emma", label: "bf_emma (EN-GB, F)" },
    { value: "bm_george", label: "bm_george (EN-GB, M)" },
  ],
  piper: [
    { value: "en_US-lessac-medium", label: "lessac medium (EN-US)" },
    { value: "en_GB-alan-medium", label: "alan medium (EN-GB)" },
  ],
  coqui: [
    {
      value: "tts_models/en/ljspeech/tacotron2-DDC",
      label: "LJSpeech Tacotron2",
    },
  ],
  elevenlabs: [
    { value: "rachel", label: "Rachel" },
    { value: "adam", label: "Adam" },
  ],
  openai: [
    { value: "alloy", label: "Alloy" },
    { value: "echo", label: "Echo" },
    { value: "fable", label: "Fable" },
    { value: "nova", label: "Nova" },
    { value: "onyx", label: "Onyx" },
    { value: "shimmer", label: "Shimmer" },
  ],
};

export const sttProviders = [
  { value: "whisper", label: "Whisper (Local)" },
  { value: "whisper-api", label: "Whisper API (Remote)" },
  { value: "deepgram", label: "Deepgram (Remote)" },
];

export const sttLanguages = [
  { value: "en", label: "English" },
  { value: "es", label: "Spanish" },
  { value: "fr", label: "French" },
  { value: "de", label: "German" },
  { value: "ja", label: "Japanese" },
  { value: "zh", label: "Chinese" },
  { value: "auto", label: "Auto-detect" },
];
