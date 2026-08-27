import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Speech recognition via the browser-native Web Speech API.
 *
 * This is the *other* direction of BridgeTalk: the hearing participant speaks,
 * and their words appear as captions for the deaf participant. Video calls have
 * done this for years; the novel half of this project is the sign direction.
 *
 * WHY THE BROWSER API RATHER THAN WHISPER
 * ---------------------------------------
 * Whisper is more accurate, especially with accents, and it would run offline.
 * It also needs a model download, a GPU to be fast, and a server round trip per
 * chunk of audio. The Web Speech API is already in the browser, streams results
 * word by word with no perceptible delay, and costs us nothing.
 *
 * The honest trade-off: in Chrome it is not local. Audio is sent to Google's
 * servers for recognition. For an accessibility tool handling private
 * conversations that is a genuine privacy cost, and it sits oddly beside our
 * "video never leaves your machine" claim for the sign direction. It is
 * documented rather than glossed over, and Whisper is the stated upgrade path.
 *
 * SUPPORT: Chrome and Edge implement this. Firefox does not, and Safari's
 * support is partial. `isSupported` is returned so the UI can say so plainly
 * instead of appearing broken.
 */

// Chrome exposes it prefixed; the standard name is there for future browsers.
const SpeechRecognitionClass =
  typeof window !== 'undefined'
    ? window.SpeechRecognition ?? window.webkitSpeechRecognition
    : undefined;

export function useSpeechToText({ enabled = false, language = 'en-US', onResult } = {}) {
  const recognitionRef = useRef(null);
  const shouldListenRef = useRef(false);

  const [listening, setListening] = useState(false);
  const [interimText, setInterimText] = useState('');
  const [error, setError] = useState(null);

  const isSupported = Boolean(SpeechRecognitionClass);

  // Held in a ref so a new callback identity does not tear down recognition
  // mid-sentence on every parent render.
  const onResultRef = useRef(onResult);
  useEffect(() => {
    onResultRef.current = onResult;
  }, [onResult]);

  useEffect(() => {
    if (!isSupported || !enabled) return undefined;

    const recognition = new SpeechRecognitionClass();
    recognition.lang = language;
    // continuous: keep listening after a pause, rather than stopping at the
    // first silence — this is a conversation, not a single command.
    recognition.continuous = true;
    // interimResults: emit partial text as it is heard. Captions that appear
    // word by word feel responsive; captions that appear only at the end of a
    // sentence feel broken.
    recognition.interimResults = true;

    recognition.onresult = (event) => {
      let interim = '';

      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const transcript = result[0].transcript;

        if (result.isFinal) {
          // Final results are the ones worth persisting. Interim text gets
          // revised word by word as the recogniser hears more, so writing it
          // to the transcript would fill the record with half-sentences.
          onResultRef.current?.({
            text: transcript.trim(),
            isFinal: true,
            confidence: result[0].confidence,
          });
        } else {
          interim += transcript;
        }
      }

      setInterimText(interim);
      if (interim) {
        onResultRef.current?.({ text: interim.trim(), isFinal: false, confidence: null });
      }
    };

    recognition.onerror = (event) => {
      // 'no-speech' and 'aborted' are routine — someone paused, or we stopped
      // it deliberately. Surfacing those as errors would make the UI cry wolf.
      if (event.error === 'no-speech' || event.error === 'aborted') return;

      if (event.error === 'not-allowed') {
        setError('Microphone permission denied. Allow it in your browser and try again.');
        shouldListenRef.current = false;
      } else if (event.error === 'network') {
        setError('Speech recognition needs a network connection and could not reach it.');
      } else {
        setError(`Speech recognition error: ${event.error}`);
      }
    };

    recognition.onend = () => {
      setListening(false);
      // Chrome stops recognition on its own after a stretch of silence, even
      // with continuous=true. Restarting keeps captions alive for the length
      // of a real meeting rather than the first ~60 seconds.
      if (shouldListenRef.current) {
        try {
          recognition.start();
          setListening(true);
        } catch {
          // start() throws if it is already running; harmless.
        }
      }
    };

    recognition.onstart = () => {
      setListening(true);
      setError(null);
    };

    recognitionRef.current = recognition;

    return () => {
      shouldListenRef.current = false;
      recognition.onend = null; // stop the auto-restart before aborting
      recognition.abort();
      recognitionRef.current = null;
      setListening(false);
      setInterimText('');
    };
  }, [enabled, isSupported, language]);

  const start = useCallback(() => {
    if (!recognitionRef.current) return;
    shouldListenRef.current = true;
    try {
      recognitionRef.current.start();
    } catch {
      // Already started.
    }
  }, []);

  const stop = useCallback(() => {
    shouldListenRef.current = false;
    recognitionRef.current?.stop();
    setInterimText('');
  }, []);

  return { isSupported, listening, interimText, error, start, stop };
}
