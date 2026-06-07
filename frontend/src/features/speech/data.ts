import { createResource, type Resource } from "solid-js";
import type { SpeechSettings, CachedAudio, CacheStats } from "./model";
import {
  mockSpeechSettings,
  mockCachedAudio,
  mockCacheStats,
  ttsProviders as _ttsProviders,
  ttsVoices as _ttsVoices,
  sttProviders as _sttProviders,
  sttLanguages as _sttLanguages,
} from "./mocks";

async function fetchSettings(): Promise<SpeechSettings> {
  return mockSpeechSettings;
}

async function fetchCachedAudio(): Promise<CachedAudio[]> {
  return mockCachedAudio;
}

async function fetchCacheStats(): Promise<CacheStats> {
  return mockCacheStats;
}

export function useSpeechSettings(): Resource<SpeechSettings> {
  const [data] = createResource(fetchSettings);
  return data;
}

export function useCachedAudio(): Resource<CachedAudio[]> {
  const [data] = createResource(fetchCachedAudio);
  return data;
}

export function useSpeechCacheStats(): Resource<CacheStats> {
  const [data] = createResource(fetchCacheStats);
  return data;
}

/* ── Static option lists (Phase 2: fetch from /api/speech/providers) ────── */
export const ttsProviders = _ttsProviders;
export const ttsVoices = _ttsVoices;
export const sttProviders = _sttProviders;
export const sttLanguages = _sttLanguages;
