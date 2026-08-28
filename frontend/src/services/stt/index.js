import { SttProvider } from './SttProvider';
import { WebSpeechProvider } from './WebSpeechProvider';
import { WhisperProvider } from './WhisperProvider';

/**
 * Provider selection and browser-support detection.
 *
 * PROBLEM: browser support. The Web Speech API is Chromium-only in practice —
 * Firefox has none and Safari's is partial and unreliable. Rather than letting
 * the caption bar sit silently empty in those browsers, `resolveProvider`
 * falls back to Whisper automatically and reports WHICH provider was chosen so
 * the UI can say so plainly.
 */

export const PROVIDERS = {
  webspeech: {
    id: 'webspeech',
    label: 'Web Speech',
    Provider: WebSpeechProvider,
    // Honest about the trade-off, shown in the UI rather than buried here.
    note: 'Fast, word-by-word. Chrome/Edge only. Audio is sent to Google.',
  },
  whisper: {
    id: 'whisper',
    label: 'Whisper',
    Provider: WhisperProvider,
    note: 'Runs on this project’s backend. Any browser. No partial text.',
  },
};

export const LANGUAGES = [
  { code: 'en-IN', label: 'English (India)' },
  { code: 'en-US', label: 'English (US)' },
  { code: 'en-GB', label: 'English (UK)' },
  { code: 'hi-IN', label: 'Hindi' },
  { code: 'ta-IN', label: 'Tamil' },
];

export function isProviderSupported(id) {
  return Boolean(PROVIDERS[id]?.Provider.isSupported());
}

/**
 * Pick a provider, honouring a preference where possible.
 *
 * Returns the id actually chosen along with why, so the caller can tell the
 * user "you asked for Web Speech, this browser has none, using Whisper"
 * instead of silently doing something different from what was requested.
 */
export function resolveProvider(preferred = 'webspeech') {
  if (isProviderSupported(preferred)) {
    return { id: preferred, fellBack: false, reason: null };
  }

  const fallback = Object.keys(PROVIDERS).find(
    (id) => id !== preferred && isProviderSupported(id),
  );

  if (fallback) {
    return {
      id: fallback,
      fellBack: true,
      reason:
        preferred === 'webspeech'
          ? 'This browser has no Web Speech API, so Whisper is being used instead.'
          : `The ${PROVIDERS[preferred].label} provider is unavailable here.`,
    };
  }

  return {
    id: null,
    fellBack: false,
    reason: 'No speech provider works in this browser.',
  };
}

export function createProvider(id, options) {
  const entry = PROVIDERS[id];
  if (!entry) throw new Error(`Unknown speech provider: ${id}`);
  return new entry.Provider(options);
}

export { SttProvider, WebSpeechProvider, WhisperProvider };
