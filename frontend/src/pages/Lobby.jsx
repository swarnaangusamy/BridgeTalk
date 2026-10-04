import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { useAuth } from '../context/AuthContext';
import { useMediaDevices } from '../hooks/useMediaDevices';
import { meetings as meetingsApi } from '../services/api';

/**
 * Pre-join lobby: see yourself, pick your devices, then enter.
 *
 * WHY THIS SCREEN EXISTS AT ALL
 * -----------------------------
 * Two reasons, and the second is specific to this project:
 *
 *   1. Nobody wants to discover their camera is off, or pointed at the
 *      ceiling, in front of an interviewer.
 *   2. **Interview mode requires camera and microphone permission before it
 *      can start.** Granting permission here, in a calm screen with an
 *      explanation, avoids a permission prompt appearing mid-interview and
 *      being counted as a focus violation.
 *
 * It also warms up the slow parts — getUserMedia and the device list — before
 * the meeting room has to do anything time-sensitive.
 */
export default function Lobby() {
  const { code } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();

  const videoRef = useRef(null);
  const streamRef = useRef(null);

  const [meeting, setMeeting] = useState(null);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState('starting'); // starting|ready|denied|error
  const [cameraOn, setCameraOn] = useState(true);
  const [micOn, setMicOn] = useState(true);
  const [cameraId, setCameraId] = useState('');
  const [microphoneId, setMicrophoneId] = useState('');
  const [joining, setJoining] = useState(false);

  const devices = useMediaDevices({ enabled: true });

  // --- meeting details -----------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    meetingsApi
      .get(code)
      .then((found) => !cancelled && setMeeting(found))
      .catch((cause) => !cancelled && setError(cause.message ?? 'Meeting not found'));
    return () => {
      cancelled = true;
    };
  }, [code]);

  // --- preview stream ------------------------------------------------------
  const startPreview = useCallback(async () => {
    // Stop the previous stream before opening another, or the camera light
    // stays on for an orphaned track and some devices refuse the second open.
    streamRef.current?.getTracks().forEach((track) => track.stop());

    setStatus('starting');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: cameraId ? { deviceId: { exact: cameraId } } : true,
        audio: microphoneId
          ? {
              deviceId: { exact: microphoneId },
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            }
          : { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });

      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }
      setStatus('ready');
      // Labels are only populated once permission has been granted, so the
      // device list is re-read now rather than at mount.
      devices.refresh();
    } catch (cause) {
      if (cause?.name === 'NotAllowedError' || cause?.name === 'SecurityError') {
        setStatus('denied');
        setError(
          'Camera and microphone permission was denied. Click the camera icon ' +
            'in your browser’s address bar, allow access, then reload.',
        );
      } else if (cause?.name === 'NotFoundError') {
        setStatus('error');
        setError('No camera or microphone found. Is one connected?');
      } else if (cause?.name === 'NotReadableError') {
        setStatus('error');
        setError(
          'Your camera is in use by another application. Close Zoom, Teams or ' +
            'Photo Booth and try again.',
        );
      } else {
        setStatus('error');
        setError(`Could not start the camera: ${cause?.message ?? cause}`);
      }
    }
    // devices.refresh is stable; listing it would restart the preview on every
    // device change, which is exactly what we do not want mid-lobby.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId, microphoneId]);

  useEffect(() => {
    startPreview();
  }, [startPreview]);

  // Release the camera when leaving the lobby. Without this the indicator
  // light stays on after navigating into the meeting, which looks like the app
  // is recording two streams.
  useEffect(
    () => () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    },
    [],
  );

  // --- toggles apply to the live preview ----------------------------------
  useEffect(() => {
    streamRef.current?.getVideoTracks().forEach((track) => {
      track.enabled = cameraOn;
    });
  }, [cameraOn, status]);

  useEffect(() => {
    streamRef.current?.getAudioTracks().forEach((track) => {
      track.enabled = micOn;
    });
  }, [micOn, status]);

  const join = useCallback(async () => {
    setJoining(true);
    try {
      await meetingsApi.join(code);
      // The chosen devices are handed to the meeting room through the URL, so
      // a reload inside the meeting keeps them rather than silently reverting
      // to the system default.
      const params = new URLSearchParams();
      if (cameraId) params.set('camera', cameraId);
      if (microphoneId) params.set('mic', microphoneId);
      if (!cameraOn) params.set('cameraOff', '1');
      if (!micOn) params.set('micOff', '1');
      const query = params.toString();
      navigate(`/meeting/${encodeURIComponent(code)}${query ? `?${query}` : ''}`);
    } catch (cause) {
      setJoining(false);
      setError(cause.message ?? 'Could not join this meeting');
    }
  }, [code, cameraId, microphoneId, cameraOn, micOn, navigate]);

  return (
    <main className="mx-auto max-w-4xl p-6">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Ready to join?</h1>
        <p className="mt-1 text-sm text-slate-400">
          <span className="font-mono">{code}</span>
          {meeting?.title && <> · {meeting.title}</>}
          {meeting?.host?.name && <> · hosted by {meeting.host.name}</>}
        </p>
      </header>

      {meeting?.is_interview_mode && (
        <p
          className="mb-4 rounded-lg border border-signal-warn/50 bg-signal-warn/10 p-3 text-sm text-slate-100"
          role="status"
        >
          <strong>Interview mode is on for this meeting.</strong> When you join,
          the meeting will go fullscreen and leaving the tab will be detected,
          reported to the host, and recorded. Allowing camera and microphone
          access here means you will not get a permission prompt mid-interview.
        </p>
      )}

      {error && (
        <p
          className="mb-4 rounded-lg border border-signal-bad/40 bg-signal-bad/10 p-3 text-sm text-signal-bad"
          role="alert"
        >
          {error}
        </p>
      )}

      <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_20rem]">
        {/* --- preview --------------------------------------------------- */}
        <section aria-labelledby="preview-heading">
          <h2 id="preview-heading" className="sr-only">
            Camera preview
          </h2>
          <div className="relative overflow-hidden rounded-xl border border-ink-700 bg-ink-900">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              // Mirrored, because an un-mirrored self-view feels wrong to
              // everyone — it is the convention in every video tool.
              className="aspect-video w-full scale-x-[-1] object-cover"
            />

            {status === 'starting' && (
              <p className="absolute inset-0 flex items-center justify-center text-slate-400" role="status">
                Starting your camera…
              </p>
            )}
            {!cameraOn && status === 'ready' && (
              <p className="absolute inset-0 flex items-center justify-center bg-ink-900/90 text-slate-300">
                Camera is off
              </p>
            )}
            {(status === 'denied' || status === 'error') && (
              <div className="absolute inset-0 flex items-center justify-center p-6 text-center">
                <p className="text-sm text-slate-300">
                  No preview available. You can still join — the meeting will
                  ask again.
                </p>
              </div>
            )}

            <p className="absolute bottom-2 left-3 rounded bg-ink-900/80 px-2 py-0.5 text-sm text-slate-200">
              {user?.name ?? 'You'}
            </p>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setCameraOn((value) => !value)}
              aria-pressed={cameraOn}
              className="rounded-lg border border-ink-700 px-3 py-2 text-sm hover:bg-ink-700"
            >
              {cameraOn ? 'Turn camera off' : 'Turn camera on'}
            </button>
            <button
              type="button"
              onClick={() => setMicOn((value) => !value)}
              aria-pressed={micOn}
              className="rounded-lg border border-ink-700 px-3 py-2 text-sm hover:bg-ink-700"
            >
              {micOn ? 'Mute microphone' : 'Unmute microphone'}
            </button>
          </div>
        </section>

        {/* --- devices + join ------------------------------------------- */}
        <aside className="flex flex-col gap-4">
          <section className="panel" aria-labelledby="devices-heading">
            <h2
              id="devices-heading"
              className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400"
            >
              Devices
            </h2>

            {devices.permission !== 'granted' && (
              <p className="mb-3 text-xs text-slate-400">
                Device names appear once you allow camera access — browsers hide
                them until then, so a site you have never permitted cannot learn
                what hardware you own.
              </p>
            )}

            <label className="mb-3 block text-xs text-slate-400">
              Camera
              <select
                value={cameraId}
                onChange={(event) => setCameraId(event.target.value)}
                className="mt-1 w-full rounded-md border border-ink-700 bg-ink-900 px-2 py-1.5 text-sm text-slate-100"
              >
                <option value="">System default</option>
                {devices.cameras.map((device, index) => (
                  <option key={device.deviceId || index} value={device.deviceId}>
                    {device.label || `Camera ${index + 1}`}
                  </option>
                ))}
              </select>
            </label>

            <label className="block text-xs text-slate-400">
              Microphone
              <select
                value={microphoneId}
                onChange={(event) => setMicrophoneId(event.target.value)}
                className="mt-1 w-full rounded-md border border-ink-700 bg-ink-900 px-2 py-1.5 text-sm text-slate-100"
              >
                <option value="">System default</option>
                {devices.microphones.map((device, index) => (
                  <option key={device.deviceId || index} value={device.deviceId}>
                    {device.label || `Microphone ${index + 1}`}
                  </option>
                ))}
              </select>
            </label>

            {devices.error && (
              <p className="mt-2 text-xs text-signal-bad" role="alert">
                {devices.error}
              </p>
            )}
          </section>

          <button
            type="button"
            onClick={join}
            disabled={joining}
            className="btn-primary w-full disabled:opacity-60"
          >
            {joining ? 'Joining…' : 'Join meeting'}
          </button>

          <button
            type="button"
            onClick={() => navigate('/')}
            className="rounded-lg border border-ink-700 px-3 py-2 text-sm hover:bg-ink-700"
          >
            Cancel
          </button>
        </aside>
      </div>
    </main>
  );
}
