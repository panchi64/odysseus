/** Speech (TTS/STT) feature data contracts. */

export interface SpeechSettings {
  ttsProvider: string;
  ttsVoice: string;
  sttProvider: string;
  sttLanguage: string;
}

export interface CachedAudio {
  id: string;
  text: string;
  durationMs: number;
  provider: string;
  voice: string;
  createdAt: string;
}

export interface CacheStats {
  totalEntries: number;
  totalBytes: number;
  hitRate: number;
}
