import { FilesetResolver, HandLandmarker } from '@mediapipe/tasks-vision';
import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Runs MediaPipe HandLandmarker on a video element, in the browser.
 *
 * THIS IS WHERE THE PRIVACY CLAIM IS TRUE OR FALSE.
 *
 * Hand tracking happens here, on the user's own machine, using WebAssembly.
 * The only thing that leaves this hook is an array of 21 (x, y, z) coordinates
 * per hand. The video frame itself never goes anywhere: it is read from the
 * <video> element, handed to the WASM module, and discarded. There is no code
 * path in this file that could upload an image, and there should never be one.
 *
 * ASSET LOADING
 * -------------
 * Both the .task model and the WASM runtime are served from our own origin
 * (public/models/), copied there by scripts/setup.sh. The MediaPipe docs point
 * at a jsDelivr CDN instead; we deliberately do not, because a college network
 * that blocks CDNs would break hand tracking with a 404 and no obvious cause.
 *
 * @param {object} options
 * @param {number} options.numHands       how many hands to track (default 1)
 * @param {boolean} options.enabled       set false to release the model
 */
export function useHandLandmarker({ numHands = 1, enabled = true } = {}) {
  const landmarkerRef = useRef(null);
  const [status, setStatus] = useState('idle'); // idle | loading | ready | error
  const [error, setError] = useState(null);

  // VIDEO mode requires strictly increasing timestamps. Reusing or going
  // backwards makes MediaPipe throw, which is easy to trigger when React
  // remounts a component in StrictMode.
  const lastTimestampRef = useRef(0);

  useEffect(() => {
    if (!enabled) return undefined;

    let cancelled = false;
    let created = null;

    async function initialise() {
      setStatus('loading');
      setError(null);

      try {
        // Loads the WASM runtime. `import.meta.env.BASE_URL` keeps this working
        // if the app is ever served from a sub-path.
        const base = import.meta.env.BASE_URL ?? '/';
        const fileset = await FilesetResolver.forVisionTasks(`${base}models/wasm`);

        created = await HandLandmarker.createFromOptions(fileset, {
          baseOptions: {
            modelAssetPath: `${base}models/hand_landmarker.task`,
            // GPU where available — it is several times faster than CPU and
            // keeps the main thread free. MediaPipe falls back to CPU on its
            // own if WebGL is unavailable.
            delegate: 'GPU',
          },
          // VIDEO mode tracks the hand across frames rather than re-detecting
          // from scratch each time. That produces steadier landmarks, which
          // matters a lot: jittery landmarks become jittery predictions.
          runningMode: 'VIDEO',
          numHands,
          minHandDetectionConfidence: 0.5,
          minHandPresenceConfidence: 0.5,
          minTrackingConfidence: 0.5,
        });

        if (cancelled) {
          created.close();
          return;
        }

        landmarkerRef.current = created;
        setStatus('ready');
      } catch (cause) {
        if (cancelled) return;
        console.error('MediaPipe HandLandmarker failed to initialise', cause);
        setError(
          'Could not load the hand-tracking model. Check that ' +
            'frontend/public/models/ contains hand_landmarker.task and the wasm/ ' +
            'folder — run ./scripts/setup.sh if not.',
        );
        setStatus('error');
      }
    }

    initialise();

    return () => {
      cancelled = true;
      // Free the WASM instance. Without this, navigating between pages leaks
      // a full model per visit and the tab's memory climbs steadily.
      if (landmarkerRef.current) {
        landmarkerRef.current.close();
        landmarkerRef.current = null;
      } else if (created) {
        created.close();
      }
      setStatus('idle');
    };
  }, [numHands, enabled]);

  /**
   * Detect hands in the current video frame.
   *
   * @param {HTMLVideoElement} video
   * @returns {object|null} MediaPipe result, or null if not ready
   */
  const detect = useCallback((video) => {
    const landmarker = landmarkerRef.current;
    if (!landmarker || !video) return null;

    // readyState < 2 means no frame is decoded yet. Calling detect then throws
    // an opaque WASM error rather than returning empty.
    if (video.readyState < 2 || video.videoWidth === 0) return null;

    // Strictly increasing, even if two frames arrive within the same
    // millisecond.
    let timestamp = performance.now();
    if (timestamp <= lastTimestampRef.current) {
      timestamp = lastTimestampRef.current + 1;
    }
    lastTimestampRef.current = timestamp;

    try {
      return landmarker.detectForVideo(video, timestamp);
    } catch (cause) {
      console.error('HandLandmarker.detectForVideo failed', cause);
      return null;
    }
  }, []);

  return { detect, status, error, isReady: status === 'ready' };
}
