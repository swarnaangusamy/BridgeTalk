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

export const ENGINE_CHOICES = [
  { id: 'auto', label: 'Auto', note: 'Browser engine where available, Whisper otherwise.' },
  { id: 'webspeech', label: 'Browser', note: 'Word-by-word. Chrome/Edge only. Audio goes to Google.' },
  { id: 'whisper', label: 'Whisper', note: 'Runs on this project’s backend. Captions appear when you pause.' },
];

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
/**
 * "Auto" is the default, and it exists because the two engines are not
 * interchangeable from a user's point of view.
 *
 * Web Speech streams interim text word by word, so captions appear while you
 * are still talking. Whisper transcribes finished audio, so nothing appears
 * until you pause — correct, but it reads as a broken feature if you were not
 * told. Auto therefore prefers Web Speech wherever it exists and falls back
 * only when it genuinely cannot run.
 *
 * Whisper must NOT be the default in Chrome or Edge, which is what the
 * reported "spoke and nothing happened" turned out to be: Whisper was
 * selected, it was waiting for an utterance to end, and the status line said
 * "listening" the whole time.
 */
export function resolveAuto() {
  if (isProviderSupported('webspeech')) {
    return {
      id: 'webspeech',
      fellBack: false,
      reason: null,
    };
  }
  if (isProviderSupported('whisper')) {
    return {
      id: 'whisper',
      fellBack: true,
      reason:
        'This browser has no Web Speech API, so Whisper is being used. ' +
        'Captions appear when you pause rather than word by word.',
    };
  }
  return { id: null, fellBack: false, reason: 'No speech engine works in this browser.' };
}

export function resolveProvider(preferred = 'auto') {
  if (preferred === 'auto') return resolveAuto();

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
