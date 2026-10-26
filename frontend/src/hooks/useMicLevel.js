import { useEffect, useRef, useState } from 'react';

/**
 * A 0–1 loudness reading from a live audio track, for the lobby's level meter.
 *
 * WHY THE METER EXISTS AT ALL
 * ---------------------------
 * "Is my microphone working?" cannot be answered by a device dropdown — a
 * selected device can still be muted in the OS, or be a virtual device with no
 * input. A bar that moves when you speak is the only honest answer, and in a
 * product whose reverse channel is speech-to-text, a dead microphone is a
 * silent failure of the main feature.
 *
 * IMPLEMENTATION NOTES
 * --------------------
 * Time-domain RMS, not `getByteFrequencyData`. RMS over the waveform is
 * amplitude, which is what "how loud am I" means; summing frequency bins
 * answers a different question and reads oddly for speech.
 *
 * `requestAnimationFrame` rather than `setInterval`: the browser pauses it in a
 * background tab, so a lobby left open does not keep an analyser running.
 *
 * The AudioContext is created per track and closed on cleanup. Browsers cap the
 * number of live contexts (Chrome at six), so leaking one per device change
 * would make the meter silently stop working after a few switches.
 *
 * Level is smoothed with an asymmetric filter — fast attack, slow release —
 * because a meter that tracks raw RMS flickers at the frame rate and reads as
 * broken rather than responsive.
 */
export function useMicLevel(stream, { enabled = true } = {}) {
  const [level, setLevel] = useState(0);
  const rafRef = useRef(null);

  // Keyed on the audio TRACK's id, not the stream object. Toggling the camera
  // replaces the stream's video track, which produces a new stream identity and
  // would otherwise tear the analyser down and rebuild it — closing and opening
  // an AudioContext — for a change that does not touch audio at all.
  const streamRef = useRef(stream);
  streamRef.current = stream;
  const audioTrackId = stream?.getAudioTracks?.()[0]?.id ?? null;

  useEffect(() => {
    const track = streamRef.current?.getAudioTracks?.()[0];
    if (!enabled || !track || track.readyState !== 'live') {
      setLevel(0);
      return undefined;
    }

    const AudioContextClass = window.AudioContext ?? window.webkitAudioContext;
    if (!AudioContextClass) return undefined;

    let context;
    let source;
    let cancelled = false;

    try {
      context = new AudioContextClass();
      // Only the audio track, in its own MediaStream. Passing the camera's
      // stream would hand the graph a video track it has no use for.
      source = context.createMediaStreamSource(new MediaStream([track]));
    } catch {
      // An AudioContext can fail outright (no output device, autoplay policy).
      // The meter is a convenience; the lobby must still work without it.
      return undefined;
    }

    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    // Deliberately NOT connected to context.destination — routing the
    // microphone to the speakers is a feedback loop.

    const samples = new Float32Array(analyser.fftSize);
    let smoothed = 0;

    const tick = () => {
      if (cancelled) return;

      analyser.getFloatTimeDomainData(samples);

      let sumOfSquares = 0;
      for (let i = 0; i < samples.length; i += 1) {
        sumOfSquares += samples[i] * samples[i];
      }
      const rms = Math.sqrt(sumOfSquares / samples.length);

      // ~3.2 scales normal speech to most of the bar without clipping on every
      // syllable; the clamp keeps a shout at 1 rather than overflowing.
      const target = Math.min(1, rms * 3.2);

      smoothed = target > smoothed
        ? smoothed + (target - smoothed) * 0.5   // attack
        : smoothed + (target - smoothed) * 0.12; // release

      setLevel(smoothed);
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelled = true;
      cancelAnimationFrame(rafRef.current);
      try {
        source.disconnect();
        analyser.disconnect();
      } catch {
        // Already torn down with the context.
      }
      context.close().catch(() => {
        // Closing can reject if the context is already closed; harmless.
      });
    };
  }, [audioTrackId, enabled]);

  return level;
}
