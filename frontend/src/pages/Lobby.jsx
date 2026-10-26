import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import {
  Avatar,
  ErrorState,
  Icon,
  IconButton,
  LoadingState,
  Logo,
  Select,
  Spinner,
} from '../components/ui';
import { useAuth } from '../context/AuthContext';
import { useMediaDevices } from '../hooks/useMediaDevices';
import { useMicLevel } from '../hooks/useMicLevel';
import { meetings as meetingsApi } from '../services/api';
import { loadDevicePreferences, saveDevicePreferences } from '../services/devicePreferences';

/**
 * The screen before the meeting: check your camera and microphone, decide
 * whether you will be signing, then join.
 *
 * WHY THE LOBBY EXISTS AT ALL
 * ---------------------------
 * The browser's camera and microphone prompt has to happen somewhere. Doing it
 * on the meeting page means the prompt appears over a live call — and in an
 * interview-mode meeting, the prompt itself takes focus from the page, which
 * the focus monitor would record as the candidate leaving the tab. The lobby
 * moves that moment somewhere calm and consequence-free.
 *
 * ONE STREAM, HANDED FORWARD
 * --------------------------
 * The preview stream is NOT stopped on the way to the meeting. It is acquired
 * here, and the meeting page acquires its own; stopping and immediately
 * re-opening the camera produces a visible half-second of black and, on some
 * webcams, an audible iris click. What IS stopped is the stream when the user
 * navigates away without joining.
 */
export default function Lobby() {
  const { code } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();

  const videoRef = useRef(null);
  const streamRef = useRef(null);

  const [meeting, setMeeting] = useState(null);
  const [meetingError, setMeetingError] = useState(null);

  const [stream, setStream] = useState(null);
  const [permissionError, setPermissionError] = useState(null);
  const [acquiring, setAcquiring] = useState(true);

  const [micOn, setMicOn] = useState(true);
  const [cameraOn, setCameraOn] = useState(true);
  const [joining, setJoining] = useState(false);

  // Restored from session storage, so a reload inside the lobby — the thing the
  // old query-parameter version existed for — keeps the user's choices.
  const saved = useRef(loadDevicePreferences()).current;
  const [micId, setMicId] = useState(saved?.micId ?? '');
  const [cameraId, setCameraId] = useState(saved?.cameraId ?? '');
  const [speakerId, setSpeakerId] = useState(saved?.speakerId ?? '');

  // Pre-ticked for someone whose account says they mostly sign, so a deaf
  // participant does not have to find a toggle before they can be understood.
  const [willSign, setWillSign] = useState(() => saved?.willSign ?? user?.role === 'deaf');

  const { cameras, microphones, speakers, refresh } = useMediaDevices({ enabled: true });
  const micLevel = useMicLevel(stream, { enabled: micOn });

  // ----------------------------------------------------------- the meeting --

  useEffect(() => {
    let cancelled = false;
    meetingsApi
      .get(code)
      .then((found) => {
        if (!cancelled) setMeeting(found);
      })
      .catch((cause) => {
        if (!cancelled) setMeetingError(cause?.message ?? 'Could not find that meeting');
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  // ------------------------------------------------------------ the camera --

  const acquire = useCallback(
    async ({ withMic, withCamera, preferredMic, preferredCamera }) => {
      setAcquiring(true);
      setPermissionError(null);

      // Stop the previous stream first. Two live streams on the same camera is
      // a NotReadableError on Windows, and the old one would keep the indicator
      // light on regardless.
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      setStream(null);

      if (!withMic && !withCamera) {
        setAcquiring(false);
        return;
      }

      try {
        const next = await navigator.mediaDevices.getUserMedia({
          video: withCamera
            ? {
                ...(preferredCamera ? { deviceId: { exact: preferredCamera } } : {}),
                width: { ideal: 640 },
                height: { ideal: 480 },
                facingMode: 'user',
              }
            : false,
          // Echo cancellation and noise suppression are requested here, not
          // only in the meeting: speech recognition runs on this microphone,
          // and the remote participant's voice coming back through it is
          // transcribed as if this user had said it.
          audio: withMic
            ? {
                ...(preferredMic ? { deviceId: { exact: preferredMic } } : {}),
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
              }
            : false,
        });

        streamRef.current = next;
        setStream(next);
        // Labels are empty until permission has been granted once, so the
        // device list is worth re-reading now that it has been.
        refresh();
      } catch (cause) {
        setPermissionError(describeMediaError(cause));
      } finally {
        setAcquiring(false);
      }
    },
    [refresh],
  );

  // First acquisition. Runs once; later changes go through the handlers, which
  // know whether the camera, the microphone or a device id changed.
  useEffect(() => {
    acquire({ withMic: true, withCamera: true, preferredMic: micId, preferredCamera: cameraId });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount only
  }, []);

  // Stop the camera when LEAVING the lobby without joining.
  //
  // `joining` is read through a ref rather than being a dependency: as a
  // dependency it would re-run this cleanup the moment Join was pressed, which
  // is exactly when the stream must survive.
  const joiningRef = useRef(false);
  joiningRef.current = joining;
  useEffect(
    () => () => {
      if (!joiningRef.current) {
        streamRef.current?.getTracks().forEach((track) => track.stop());
      }
    },
    [],
  );

  // Attach the stream to the <video>. Separate from acquisition because the
  // element does not exist on the first render when the preview is hidden.
  useEffect(() => {
    const element = videoRef.current;
    if (!element) return;
    if (element.srcObject !== stream) element.srcObject = stream ?? null;
    if (stream) element.play().catch(() => {
      // Autoplay can reject before the first user gesture. The preview is
      // muted, so this effectively never happens, and a still frame is a
      // survivable outcome if it does.
    });
  }, [stream]);

  // Route preview audio to the chosen speaker where the browser allows it.
  useEffect(() => {
    const element = videoRef.current;
    if (!element?.setSinkId || !speakerId) return;
    element.setSinkId(speakerId).catch(() => {
      // Chromium-only, and it rejects for a device that has gone away. The
      // choice is still saved and handed to the meeting.
    });
  }, [speakerId, stream]);

  // --------------------------------------------------------------- actions --

  function toggleMic() {
    const next = !micOn;
    setMicOn(next);
    // Enable/disable rather than re-acquire: the track stays open, so the level
    // meter resumes instantly instead of waiting on getUserMedia.
    streamRef.current?.getAudioTracks().forEach((track) => {
      track.enabled = next;
    });
  }

  async function toggleCamera() {
    const next = !cameraOn;
    setCameraOn(next);
    // Camera off genuinely RELEASES the device here, as it does in the meeting:
    // the indicator light must go out, or the preview is lying about the state
    // of the user's hardware.
    await acquire({
      withMic: true,
      withCamera: next,
      preferredMic: micId,
      preferredCamera: cameraId,
    });
    if (!next) return;
    streamRef.current?.getAudioTracks().forEach((track) => {
      track.enabled = micOn;
    });
  }

  async function changeMic(value) {
    setMicId(value);
    await acquire({
      withMic: true,
      withCamera: cameraOn,
      preferredMic: value,
      preferredCamera: cameraId,
    });
  }

  async function changeCamera(value) {
    setCameraId(value);
    await acquire({
      withMic: true,
      withCamera: cameraOn,
      preferredMic: micId,
      preferredCamera: value,
    });
  }

  async function join() {
    setJoining(true);
    // Saved BEFORE navigating: the meeting page reads these on mount, so a save
    // afterwards would race with it and the first meeting would use defaults.
    saveDevicePreferences({ micId, cameraId, speakerId, willSign, micOn, cameraOn });

    try {
      await meetingsApi.join(code);
      navigate(`/meeting/${code}`);
    } catch (cause) {
      setMeetingError(cause?.message ?? 'Could not join this meeting');
      setJoining(false);
    }
  }

  // ---------------------------------------------------------------- render --

  if (meetingError && !meeting) {
    return (
      <main className="grid min-h-screen place-items-center bg-light-bg p-6">
        <div className="w-full max-w-lg">
          <div className="mb-8 flex justify-center">
            <Logo to="/" />
          </div>
          <ErrorState
            title="This meeting is not available"
            body={meetingError}
            onRetry={() => navigate('/')}
            retryLabel="Back to home"
          />
        </div>
      </main>
    );
  }

  const others = (meeting?.participants ?? []).filter(
    (participant) => participant.user?.id !== user?.id && !participant.left_at,
  );

  return (
    <div className="min-h-screen bg-light-bg">
      {/* No account menu here, only the logo — the specification is explicit. */}
      <header className="flex h-topbar items-center px-4 sm:px-6">
        <Logo to="/" />
      </header>

      <main className="mx-auto max-w-6xl px-4 pb-16 sm:px-6">
        <div className="grid items-center gap-8 py-6 lg:grid-cols-[minmax(0,6fr)_minmax(0,4fr)] lg:gap-12 lg:py-12">
          {/* ------------------------- left: preview ---------------------- */}
          <section>
            {permissionError ? (
              <PermissionHelp
                error={permissionError}
                onRetry={() =>
                  acquire({
                    withMic: true,
                    withCamera: cameraOn,
                    preferredMic: micId,
                    preferredCamera: cameraId,
                  })
                }
              />
            ) : (
              <div className="relative aspect-video w-full overflow-hidden rounded-tile bg-[#202124]">
                {/* The preview is mirrored, which is what every video tool does
                    for your own image: an unmirrored self-view feels wrong
                    because it is not what a mirror shows you. */}
                <video
                  ref={videoRef}
                  autoPlay
                  playsInline
                  muted
                  className={`h-full w-full scale-x-[-1] object-cover transition-opacity
                              ${cameraOn && stream ? 'opacity-100' : 'opacity-0'}`}
                />

                {!cameraOn || !stream ? (
                  <div className="absolute inset-0 grid place-items-center gap-3">
                    {acquiring ? (
                      <Spinner size={28} className="border-white/20 border-t-white" />
                    ) : (
                      <>
                        <Avatar name={user?.name ?? ''} size={72} />
                        <p className="text-sm text-dark-muted">Camera is off</p>
                      </>
                    )}
                  </div>
                ) : null}

                {/* Name, top-left of the preview */}
                <p className="absolute left-3 top-3 max-w-[60%] truncate rounded bg-black/40 px-2 py-1 text-sm text-dark-text">
                  {user?.name}
                </p>

                {/* Live microphone level, bottom-left */}
                <div className="absolute bottom-4 left-3 flex items-center gap-2">
                  <Icon
                    name={micOn ? 'mic' : 'mic_off'}
                    size={18}
                    className={micOn ? 'text-dark-text' : 'text-dark-danger'}
                  />
                  <span
                    role="meter"
                    aria-label="Microphone level"
                    aria-valuenow={Math.round(micLevel * 100)}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    className="flex h-4 items-end gap-[3px]"
                  >
                    {[0.15, 0.35, 0.55, 0.75, 0.92].map((threshold, index) => (
                      <span
                        key={threshold}
                        className={`w-[3px] rounded-sm transition-colors duration-75
                          ${micOn && micLevel >= threshold ? 'bg-dark-accent' : 'bg-white/25'}`}
                        style={{ height: `${6 + index * 2.5}px` }}
                      />
                    ))}
                  </span>
                </div>

                {/* Mic and camera toggles, bottom centre */}
                <div className="on-dark absolute bottom-4 left-1/2 flex -translate-x-1/2 gap-3">
                  <IconButton
                    icon={micOn ? 'mic' : 'mic_off'}
                    label={micOn ? 'Turn off microphone' : 'Turn on microphone'}
                    onClick={toggleMic}
                    danger={!micOn}
                    size={44}
                    iconSize={20}
                  />
                  <IconButton
                    icon={cameraOn ? 'videocam' : 'videocam_off'}
                    label={cameraOn ? 'Turn off camera' : 'Turn on camera'}
                    onClick={toggleCamera}
                    danger={!cameraOn}
                    disabled={acquiring}
                    size={44}
                    iconSize={20}
                  />
                </div>
              </div>
            )}

            {/* Device pickers */}
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <Select
                label="Microphone"
                icon="mic"
                value={micId}
                onChange={changeMic}
                options={toOptions(microphones, 'Microphone')}
              />
              {/* Hidden when the browser exposes no output devices — Firefox and
                  Safari do not, and setSinkId is Chromium-only, so the control
                  would be decoration there. */}
              {speakers.length > 0 ? (
                <Select
                  label="Speaker"
                  icon="volume_up"
                  value={speakerId}
                  onChange={setSpeakerId}
                  options={toOptions(speakers, 'Speaker')}
                />
              ) : (
                <div className="hidden sm:block" aria-hidden="true" />
              )}
              <Select
                label="Camera"
                icon="videocam"
                value={cameraId}
                onChange={changeCamera}
                options={toOptions(cameras, 'Camera')}
              />
            </div>
          </section>

          {/* ------------------------- right: join ------------------------ */}
          <section className="lg:pl-4">
            {!meeting ? (
              <LoadingState message="Loading the meeting…" />
            ) : (
              <>
                <h1 className="text-2xl font-normal text-light-text">Ready to join?</h1>
                <p className="mt-2 text-sm text-light-muted">
                  {meeting.title}
                </p>
                <p className="mt-0.5 font-mono text-sm text-light-muted">{code}</p>

                <div className="mt-5 flex items-center gap-2">
                  {others.length === 0 ? (
                    <p className="text-sm text-light-muted">No one else is here</p>
                  ) : (
                    <>
                      <div className="flex items-center">
                        {others.slice(0, 4).map((participant, index) => (
                          <span
                            key={participant.id}
                            className="-ml-1.5 rounded-full ring-2 ring-light-bg first:ml-0"
                            style={{ zIndex: 4 - index }}
                          >
                            <Avatar name={participant.user?.name ?? ''} size={28} />
                          </span>
                        ))}
                      </div>
                      <p className="text-sm text-light-muted">
                        {others.length === 1
                          ? `${others[0].user?.name} is in this call`
                          : `${others.length} people are in this call`}
                      </p>
                    </>
                  )}
                </div>

                {meeting.is_interview_mode ? (
                  <p className="mt-5 flex items-start gap-2 rounded-card bg-light-surface p-3 text-sm text-light-muted">
                    <Icon name="policy" size={18} className="mt-px shrink-0" />
                    <span>
                      Interview mode is on for this meeting. Leaving the meeting
                      tab will be recorded and shown to the host.
                    </span>
                  </p>
                ) : null}

                <label className="mt-6 flex cursor-pointer items-start gap-3">
                  <input
                    type="checkbox"
                    checked={willSign}
                    onChange={(event) => setWillSign(event.target.checked)}
                    className="mt-0.5 h-5 w-5 shrink-0 cursor-pointer accent-light-blue"
                  />
                  <span>
                    <span className="block text-sm font-medium text-light-text">
                      I will be signing in this meeting
                    </span>
                    <span className="mt-0.5 block text-xs text-light-muted">
                      Turns on sign recognition when you join, so your signs
                      become captions for everyone. You can change this during
                      the meeting.
                    </span>
                  </span>
                </label>

                {meetingError ? (
                  <p role="alert" className="mt-4 text-sm text-light-danger">
                    {meetingError}
                  </p>
                ) : null}

                <div className="mt-7 flex items-center gap-3">
                  <button
                    type="button"
                    onClick={join}
                    disabled={joining}
                    className="btn-primary h-12 px-7"
                  >
                    {joining ? (
                      <Spinner size={16} className="border-white/40 border-t-white" />
                    ) : null}
                    Join now
                  </button>
                  <Link to="/" className="btn-text">
                    Back to home
                  </Link>
                </div>
              </>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}

/** Device list to Select options, with a readable fallback for unlabelled ones. */
function toOptions(devices, kind) {
  return devices.map((device, index) => ({
    value: device.deviceId,
    label: device.label || `${kind} ${index + 1}`,
  }));
}

/**
 * Turn a getUserMedia rejection into something a user can act on.
 *
 * The browser's own messages are written for developers — "Could not start
 * video source" tells someone nothing about what to do next. The distinction
 * that matters is denied-by-choice versus device-in-use-elsewhere, because the
 * fixes are completely different.
 */
function describeMediaError(cause) {
  const name = cause?.name ?? '';

  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return {
      title: 'BridgeTalk needs your camera and microphone',
      steps: [
        'Click the camera or lock icon in your browser address bar.',
        'Set Camera and Microphone to Allow for this site.',
        'Then choose Try again below.',
      ],
    };
  }

  if (name === 'NotFoundError' || name === 'OverconstrainedError') {
    return {
      title: 'No camera or microphone was found',
      steps: [
        'Check that your camera and microphone are plugged in.',
        'If you have just connected one, choose Try again.',
      ],
    };
  }

  if (name === 'NotReadableError' || name === 'AbortError') {
    return {
      title: 'Your camera is being used by another app',
      steps: [
        'Close any other app using the camera — another meeting tab, Zoom, or Photo Booth.',
        'Then choose Try again.',
      ],
    };
  }

  return {
    title: 'Could not start your camera and microphone',
    steps: [cause?.message ?? 'An unknown error occurred.', 'Choose Try again to retry.'],
  };
}

function PermissionHelp({ error, onRetry }) {
  return (
    <div className="grid aspect-video w-full place-items-center rounded-tile border border-light-border bg-light-surface p-6">
      <div className="max-w-sm text-center">
        <span aria-hidden="true" className="text-light-muted">
          <Icon name="videocam_off" size={36} />
        </span>
        <h2 className="mt-3 text-base font-medium text-light-text">{error.title}</h2>
        <ol className="mt-3 list-decimal space-y-1 pl-5 text-left text-sm text-light-muted">
          {error.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        <button type="button" onClick={onRetry} className="btn-primary mt-5">
          Try again
        </button>
      </div>
    </div>
  );
}
