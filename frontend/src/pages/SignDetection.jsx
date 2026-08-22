import { useCallback, useEffect, useRef, useState } from 'react';

import HandOverlayCanvas from '../components/HandOverlayCanvas';
import SignDetectionPanel from '../components/SignDetectionPanel';
import { useAuth } from '../context/AuthContext';
import { useHandLandmarker } from '../hooks/useHandLandmarker';
import { useSignSocket } from '../hooks/useSignSocket';
import { toWireFormat } from '../utils/landmarkUtils';

/**
 * The Phase 5 screen: webcam in, recognised text out, in the browser.
 *
 * THE LOOP
 * --------
 *   requestAnimationFrame (~60 Hz)
 *     -> MediaPipe detect on the current frame      (every frame, local)
 *     -> draw the skeleton                          (every frame, local)
 *     -> send landmarks over the WebSocket          (throttled to ~10 Hz)
 *
 * Detection runs at full frame rate because the overlay has to look smooth,
 * and it costs nothing but local CPU. Sending is throttled to 10 Hz because
 * that is all the recognition needs: the smoothing layer votes over a 10-frame
 * window, which at 10 Hz is a one-second decision — about how long a person
 * holds a letter. Sending at 60 Hz would sextuple the traffic and the server's
 * inference load to reach the same conclusion a second later anyway.
 */

const SEND_INTERVAL_MS = 100; // 10 FPS

export default function SignDetection() {
  const { user, logout } = useAuth();

  const videoRef = useRef(null);
  const rafRef = useRef(null);
  const lastSentRef = useRef(0);

  const [cameraStatus, setCameraStatus] = useState('idle'); // idle|starting|on|denied|error
  const [cameraError, setCameraError] = useState(null);
  const [landmarks, setLandmarks] = useState([]);
  const [detecting, setDetecting] = useState(true);
  const [mode, setMode] = useState('static');

  // ASL fingerspelling is one-handed, so tracking a second hand there would be
  // wasted work. ISL fingerspelling and word signs both use two, and their
  // 126-wide features have a slot for each — tracking only one would leave half
  // of every input vector zero.
  const { detect, status: modelStatus, error: modelError, isReady } = useHandLandmarker({
    numHands: mode === 'static' ? 1 : 2,
    enabled: true,
  });

  // 'DEMO' is a reserved code that skips the meeting lookup but still requires
  // a valid token — it lets sign detection be exercised before any meeting
  // exists. Phase 6 replaces this with the real meeting code.
  const {
    status: socketStatus,
    prediction,
    sentence,
    serverError,
    modelInfo,
    dynamicModelInfo,
    islModelInfo,
    sendLandmarks,
    clearSentence,
    backspace,
  } = useSignSocket({ meetingCode: 'DEMO', enabled: true });

  // --- camera --------------------------------------------------------------
  useEffect(() => {
    let stream = null;
    let cancelled = false;

    async function startCamera() {
      setCameraStatus('starting');
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
          audio: false,
        });

        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
        setCameraStatus('on');
      } catch (error) {
        if (cancelled) return;

        // These names are worth distinguishing: the fixes are completely
        // different, and "could not start camera" helps nobody.
        if (error.name === 'NotAllowedError' || error.name === 'SecurityError') {
          setCameraStatus('denied');
          setCameraError(
            'Camera permission was denied. Click the camera icon in your browser’s ' +
              'address bar and allow access, then reload.',
          );
        } else if (error.name === 'NotFoundError') {
          setCameraStatus('error');
          setCameraError('No camera found. Is one connected?');
        } else if (error.name === 'NotReadableError') {
          setCameraStatus('error');
          setCameraError(
            'The camera is in use by another application. Close Zoom, Teams or ' +
              'Photo Booth and reload.',
          );
        } else {
          setCameraStatus('error');
          setCameraError(`Could not start the camera: ${error.message}`);
        }
      }
    }

    startCamera();

    return () => {
      cancelled = true;
      // Releasing the tracks turns the camera light off. Skipping this leaves
      // the webcam apparently recording after you navigate away, which is a
      // genuinely alarming thing for an accessibility tool to do.
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  // --- detection loop ------------------------------------------------------
  useEffect(() => {
    if (cameraStatus !== 'on' || !isReady || !detecting) return undefined;

    let active = true;

    const tick = () => {
      if (!active) return;

      const result = detect(videoRef.current);

      if (result?.landmarks?.length) {
        setLandmarks(result.landmarks);

        const now = performance.now();
        if (now - lastSentRef.current >= SEND_INTERVAL_MS) {
          lastSentRef.current = now;
          // toWireFormat produces coordinates only. No pixel data is included,
          // and there is nowhere in this call for a frame to hide.
          sendLandmarks(toWireFormat(result), mode);
        }
      } else {
        setLandmarks([]);

        // Still tell the server about empty frames, throttled the same way:
        // that is what drives the neutral reset and lets lowering your hand
        // close the current word. In dynamic mode it is also what marks the
        // boundary between two signs.
        const now = performance.now();
        if (now - lastSentRef.current >= SEND_INTERVAL_MS) {
          lastSentRef.current = now;
          sendLandmarks([], mode);
        }
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);

    return () => {
      active = false;
      cancelAnimationFrame(rafRef.current);
    };
  }, [cameraStatus, isReady, detecting, detect, sendLandmarks, mode]);

  const handDetected = landmarks.length > 0;

  const toggleDetection = useCallback(() => {
    setDetecting((current) => !current);
    setLandmarks([]);
  }, []);

  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">BridgeTalk — sign detection</h1>
          <p className="mt-1 text-slate-300">
            Hand tracking runs in your browser. Only landmark coordinates are sent to the
            server — your video never leaves this machine.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-slate-300">{user?.name}</span>
          <button type="button" onClick={logout}
                  className="rounded-md border border-ink-700 px-3 py-1.5 text-sm hover:bg-ink-700">
            Log out
          </button>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
        {/* --- video + overlay ---------------------------------------- */}
        <section aria-labelledby="camera-heading">
          <h2 id="camera-heading" className="sr-only">
            Camera preview with hand tracking overlay
          </h2>

          <div className="relative aspect-[4/3] overflow-hidden rounded-xl border border-ink-700 bg-ink-900">
            <video
              ref={videoRef}
              playsInline
              muted
              // Mirrored so that moving your hand right moves it right on
              // screen. An un-mirrored preview is genuinely disorienting to
              // sign into — you correct the wrong way.
              className="h-full w-full -scale-x-100 object-cover"
            />

            <HandOverlayCanvas
              landmarks={landmarks}
              mirrored
              stable={prediction?.stable ?? false}
            />

            {/* Explicit, visible states rather than a blank rectangle. */}
            {cameraStatus === 'starting' && (
              <p className="absolute inset-0 grid place-items-center text-slate-300">
                Starting camera…
              </p>
            )}

            {(cameraStatus === 'denied' || cameraStatus === 'error') && (
              <div className="absolute inset-0 grid place-items-center p-6" role="alert">
                <p className="max-w-sm text-center text-signal-bad">{cameraError}</p>
              </div>
            )}

            {cameraStatus === 'on' && modelStatus === 'loading' && (
              <p className="absolute inset-0 grid place-items-center bg-ink-900/60 text-slate-200">
                Loading hand-tracking model…
              </p>
            )}

            {modelStatus === 'error' && (
              <div className="absolute inset-0 grid place-items-center p-6" role="alert">
                <p className="max-w-sm text-center text-signal-bad">{modelError}</p>
              </div>
            )}

            {cameraStatus === 'on' && isReady && !detecting && (
              <p className="absolute inset-0 grid place-items-center bg-ink-900/60 text-slate-200">
                Detection paused
              </p>
            )}
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button type="button" onClick={toggleDetection} className="btn-primary">
              {detecting ? 'Pause detection' : 'Resume detection'}
            </button>
            <p className="text-sm text-slate-400">
              {handDetected ? 'Hand in frame' : 'No hand in frame'} · sending at{' '}
              {1000 / SEND_INTERVAL_MS} FPS
            </p>
          </div>
        </section>

        {/* --- prediction panel --------------------------------------- */}
        <SignDetectionPanel
          status={socketStatus}
          prediction={prediction}
          sentence={sentence}
          serverError={serverError}
          modelInfo={modelInfo}
          dynamicModelInfo={dynamicModelInfo}
          islModelInfo={islModelInfo}
          handDetected={handDetected}
          mode={mode}
          onModeChange={setMode}
          onClear={clearSentence}
          onBackspace={backspace}
        />
      </div>

      <section className="panel mt-6">
        <h2 className="text-lg font-semibold">Tips for a good result</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-300">
          <li>Light on your hand, not behind it. A window behind you makes a silhouette.</li>
          <li>Keep your whole hand in frame, roughly filling a third of the width.</li>
          <li>Hold each letter still for about a second — the smoothing needs ~7 frames.</li>
          <li>
            Start with <strong>A, B, L, Y, W</strong>. M, N, R and U are the model’s known
            weak spots and are documented as such.
          </li>
        </ul>
      </section>
    </main>
  );
}
