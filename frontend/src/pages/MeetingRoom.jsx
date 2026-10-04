import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import HandOverlayCanvas from '../components/HandOverlayCanvas';
import {
  CaptionSizeControl,
  CopyLinkButton,
  MeetingTimer,
  useCaptionSize,
} from '../components/MeetingHeaderControls';
import InterviewModeDialog from '../components/InterviewModeDialog';
import InterviewModeOverlay from '../components/InterviewModeOverlay';
import CaptionArea from '../components/CaptionArea';
import DebugOverlay from '../components/DebugOverlay';
import VideoTile from '../components/VideoTile';
import { useAuth } from '../context/AuthContext';
import { useCaptionStore } from '../hooks/useCaptionStore';
import { useInterviewMode } from '../hooks/useInterviewMode';
import { useSignCaptions } from '../hooks/useSignCaptions';
import { useSpeechCaptions } from '../hooks/useSpeechCaptions';
import { useHandLandmarker } from '../hooks/useHandLandmarker';
import { useSignSocket } from '../hooks/useSignSocket';
import { useWebRTC } from '../hooks/useWebRTC';
import { loadDevicePreferences } from '../services/devicePreferences';
import { meetings as meetingsApi, transcripts as transcriptsApi } from '../services/api';
import { toWireFormat } from '../utils/landmarkUtils';

/**
 * The main screen: a 1:1 call with translation running in both directions.
 *
 * FOUR THINGS RUN AT ONCE HERE, AND THEY SHARE ONE CAMERA
 * -------------------------------------------------------
 *   1. MediaPipe reads the local video element for hand landmarks (local only)
 *   2. those landmarks stream to /ws/predict and come back as text
 *   3. the same MediaStream is published to the peer over WebRTC
 *   4. the Web Speech API captions the microphone for the other direction
 *
 * getUserMedia is called exactly once and the resulting stream is shared.
 * Calling it twice would ask for the camera twice and, on some machines,
 * fail outright because the device is already open.
 */

const SEND_INTERVAL_MS = 100; // 10 FPS to the inference socket

// Violations before the host is prompted to remove the participant.
// Configurable here rather than scattered through the UI.
const MAX_VIOLATIONS = 3;

export default function MeetingRoom() {
  const { code } = useParams();
  const [searchParams] = useSearchParams();
  const captionSize = useCaptionSize();
  // ?debug=1 only. "I spoke and nothing happened" is not a reportable bug
  // without knowing which stage died.
  const debugEnabled = searchParams.get('debug') === '1';
  const lastSentRef2 = useRef('—');
  const lastReceivedRef = useRef('—');
  const navigate = useNavigate();
  const { user } = useAuth();

  const localVideoRef = useRef(null);
  const rafRef = useRef(null);
  const lastSentRef = useRef(0);

  const [meeting, setMeeting] = useState(null);
  const [localStream, setLocalStream] = useState(null);
  const [cameraError, setCameraError] = useState(null);
  const [landmarks, setLandmarks] = useState([]);

  // Sign recognition is OPT-IN and OFF by default. It used to default to true
  // for everyone, which is why the hearing participant's resting hands were
  // being classified as signs ("M at 71%") while they were not signing at all.
  const [signRecognitionOn, setSignRecognitionOn] = useState(false);
  // Captions are DISPLAY only, and on by default for everyone.
  const [captionsVisible, setCaptionsVisible] = useState(true);
  const [recognitionMode, setRecognitionMode] = useState('static');
  const [micOn, setMicOn] = useState(true);
  const [cameraOn, setCameraOn] = useState(true);
  // en-IN by default: the demo is in India, and the Indian English
  // acoustic model recognises local accents markedly better than en-US.
  const [speechLanguage, setSpeechLanguage] = useState('en-IN');
  // 'auto' prefers the browser engine, which streams interim text word by
  // word. Whisper only emits when you pause, which reads as a dead feature if
  // it is what you get by default in Chrome.
  const [speechEngine, setSpeechEngine] = useState('auto');
  const [transcriptCollapsed, setTranscriptCollapsed] = useState(false);

  const [transcriptLines, setTranscriptLines] = useState([]);

  // --- meeting record ------------------------------------------------------
  useEffect(() => {
    let cancelled = false;

    async function joinMeeting() {
      try {
        const result = await meetingsApi.join(code);
        if (!cancelled) setMeeting(result.meeting);

        const existing = await transcriptsApi.list(result.meeting.id);
        if (!cancelled) {
          setTranscriptLines(
            existing.map((row) => ({
              id: `db-${row.id}`,
              speaker: row.user_name,
              source: row.source,
              text: row.content,
              confidence: row.confidence,
              timestamp: row.created_at,
            })),
          );
        }
      } catch (error) {
        // Already in the meeting, or it has ended — fall back to a read so the
        // room still renders rather than dumping the user back to the dashboard.
        try {
          const detail = await meetingsApi.get(code);
          if (!cancelled) setMeeting(detail);
        } catch {
          if (!cancelled) navigate('/', { replace: true });
        }
      }
    }

    joinMeeting();
    return () => {
      cancelled = true;
    };
  }, [code, navigate]);

  // --- one camera, shared ---------------------------------------------------
  useEffect(() => {
    let stream = null;
    let cancelled = false;

    async function startMedia() {
      try {
        // Devices chosen in the lobby arrive as query parameters, so a reload
        // inside the meeting keeps them instead of silently reverting to the
        // system default. `exact` is used deliberately: without it the browser
        // treats the id as a preference and may hand back a different camera,
        // which would make the lobby's selector a lie.
        const chosenCamera = searchParams.get('camera');
        const chosenMic = searchParams.get('mic');

        stream = await navigator.mediaDevices.getUserMedia({
          video: chosenCamera
            ? { deviceId: { exact: chosenCamera }, width: { ideal: 640 }, height: { ideal: 480 } }
            : { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
          audio: chosenMic
            ? {
                deviceId: { exact: chosenMic },
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
              }
            : { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        // The lobby may have been left with the camera or mic muted. Carry
        // that through rather than surprising someone with a live camera they
        // had deliberately switched off a moment earlier.
        if (searchParams.get('cameraOff') === '1') {
          stream.getVideoTracks().forEach((track) => {
            track.enabled = false;
          });
          setCameraOn(false);
        }
        if (searchParams.get('micOff') === '1') {
          stream.getAudioTracks().forEach((track) => {
            track.enabled = false;
          });
          setMicOn(false);
        }

        setLocalStream(stream);
      } catch (error) {
        if (cancelled) return;
        if (error.name === 'NotAllowedError') {
          setCameraError(
            'Camera and microphone permission denied. Allow access in your browser’s ' +
              'address bar and reload.',
          );
        } else if (error.name === 'NotReadableError') {
          setCameraError('Camera is in use by another app. Close Zoom or Teams and reload.');
        } else {
          setCameraError(`Could not start camera or microphone: ${error.message}`);
        }
      }
    }

    startMedia();
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  // Attach the stream to the local <video>, which MediaPipe then reads frames
  // from. VideoTile handles this for tiles it owns; the local tile's element is
  // shared with the detection loop, so it is wired here.
  useEffect(() => {
    if (localVideoRef.current && localStream) {
      localVideoRef.current.srcObject = localStream;
    }
  }, [localStream]);

  // --- captions ------------------------------------------------------------
  // ONE store for both sources and both participants. Every caption — mine and
  // theirs, sign and speech — arrives through the socket and is applied here
  // by segment id. Previously each side rendered its own words from local state
  // and the other person's from the socket, which is why the two screens
  // disagreed about what had been said.
  const { captions, applyCaption, clearCaptions } = useCaptionStore();

  const {
    status: signSocketStatus,
    prediction,
    serverError: signError,
    modelInfo,
    dynamicModelInfo,
    islModelInfo,
    sendLandmarks,
    sendCaption,
  } = useSignSocket({
    meetingCode: code,
    enabled: Boolean(meeting),
    onCaption: applyAndRecord,
  });

  // Producers hand captions to the socket. They never touch the store
  // directly: the round trip through the server is what guarantees both
  // participants see identical text, and it is also what persists it.
  const emitCaption = useCallback(
    (caption) => {
      lastSentRef2.current = `${caption.source}/${caption.isFinal ? 'final' : 'interim'}: ${caption.text.slice(0, 28)}`;
      sendCaption(caption);
    },
    [sendCaption],
  );

  const applyAndRecord = useCallback(
    (event) => {
      lastReceivedRef.current = `${event.source}/${event.is_final ? 'final' : 'interim'}: ${(event.text ?? '').slice(0, 28)}`;
      applyCaption(event);
    },
    [applyCaption],
  );

  // One hand for ASL fingerspelling, two for ISL fingerspelling and word signs.
  // Their features have a slot per hand, and tracking only one would leave half
  // of every input zero. See RecognitionModeToggle for why these are separate
  // modes rather than a language setting.
  const { detect, status: landmarkerStatus, error: landmarkerError, isReady } =
    useHandLandmarker({
      numHands: recognitionMode === 'static' ? 1 : 2,
      enabled: signRecognitionOn,
    });

  useEffect(() => {
    // Gated on the camera as well as the sign toggle. Tracking a released
    // camera is what left a frozen skeleton on screen.
    if (!localStream || !isReady || !signRecognitionOn || !cameraOn) {
      // Clear any skeleton left from the last frame we did process, so the
      // overlay cannot outlive the video it was drawn from.
      setLandmarks([]);
      return undefined;
    }

    let active = true;
    const tick = () => {
      if (!active) return;

      const result = detect(localVideoRef.current);
      const now = performance.now();
      const shouldSend = now - lastSentRef.current >= SEND_INTERVAL_MS;

      if (result?.landmarks?.length) {
        setLandmarks(result.landmarks);
        if (shouldSend) {
          lastSentRef.current = now;
          sendLandmarks(toWireFormat(result), recognitionMode);
        }
      } else {
        setLandmarks([]);
        if (shouldSend) {
          lastSentRef.current = now;
          // Empty frames matter: they drive the neutral reset that closes a
          // word when the signer lowers their hand, and in dynamic mode they
          // are what marks the boundary between two signs.
          sendLandmarks([], recognitionMode);
        }
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      active = false;
      cancelAnimationFrame(rafRef.current);
    };
  }, [localStream, isReady, signRecognitionOn, cameraOn, detect, sendLandmarks, recognitionMode]);
  // --- producing sign captions ---------------------------------------------
  // Segmentation lives in useSignCaptions, not in a server-side smoother and
  // not in this component. The old code committed a word every time a 2.5 s
  // cooldown lapsed, which is why one held pose produced "warm warm warm" —
  // a timer cannot tell "still signing this" from "signed it again". The hook
  // watches hand MOTION instead, commits once per movement, and refuses to
  // repeat a token until the hands have returned to rest.
  const signCaptions = useSignCaptions({
    enabled: Boolean(signRecognitionOn && cameraOn && meeting),
    mode: recognitionMode,
    prediction,
    landmarks,
    onCaption: emitCaption,
  });

  // --- producing speech captions -------------------------------------------
  // Keyed to ONE thing: is my microphone unmuted. Not to a panel toggle.
  //
  // Recognition used to be gated on a `speechOn` flag that defaulted to OFF,
  // so a participant who never found that toggle produced no captions at all —
  // while the panel still said "listening", because that reported the
  // recogniser object's state rather than whether any audio reached it. That
  // is the reported "spoke and nothing happened".
  //
  // Producing is now automatic; the captions button only controls DISPLAY.
  // Nobody's speech should go unrecognised because they chose not to look at
  // captions themselves.
  const speech = useSpeechCaptions({
    enabled: Boolean(micOn && meeting),
    engine: speechEngine,
    language: speechLanguage,
    meetingCode: code,
    onCaption: emitCaption,
  });

  // --- keyboard shortcuts --------------------------------------------------
  // Ctrl/Cmd+D microphone, Ctrl/Cmd+E camera, C captions. Skipped while focus
  // is in a text field, or typing a meeting code would toggle the mic.
  useEffect(() => {
    const handler = (event) => {
      const tag = event.target?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      const modifier = event.ctrlKey || event.metaKey;
      if (modifier && event.key.toLowerCase() === 'd') {
        event.preventDefault();
        toggleMic();
      } else if (modifier && event.key.toLowerCase() === 'e') {
        event.preventDefault();
        toggleCamera();
      } else if (!modifier && event.key.toLowerCase() === 'c') {
        setCaptionsVisible((value) => !value);
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [toggleCamera]);

  // --- Interview Mode ------------------------------------------------------
  // The mode lives on the MEETING RECORD, not in local state, so a participant
  // who reloads or reconnects arrives already subject to it. Reloading must not
  // be a way out.
  const isHost = Boolean(meeting?.host?.id && user?.id && meeting.host.id === user.id);
  const interviewOn = Boolean(meeting?.is_interview_mode);

  // Each focus change is posted to the backend so the record survives a page
  // reload — a tab switch the participant then refreshes away should still be
  // in the host's log.
  const handleViolation = useCallback(
    ({ type, durationMs }) => {
      if (!interviewOn) return;
      meetingsApi.logFocusEvent(code, type, durationMs).catch(() => {
        // Best effort. A failed log must never interrupt the meeting itself.
      });
    },
    [code, interviewOn],
  );

  const interview = useInterviewMode({
    enabled: interviewOn,
    isHost,
    onViolation: handleViolation,
    maxViolations: MAX_VIOLATIONS,
  });

  // The host's live view of who has left and how often.
  const [violationLog, setViolationLog] = useState([]);

  const refreshViolations = useCallback(() => {
    if (!isHost || !interviewOn) return;
    meetingsApi
      .focusEvents(code)
      .then((summary) => setViolationLog(summary.by_participant ?? []))
      .catch(() => {
        /* the host's panel is informational; a failure must not break the call */
      });
  }, [code, interviewOn, isHost]);

  // Polled rather than pushed. The violation feed is a host-only side panel,
  // and adding a third message type to the inference socket to carry it would
  // couple attention logging to sign recognition — a failure in one would then
  // take down the other. Five seconds is well inside human reaction time for
  // something the host acts on by talking to the candidate.
  useEffect(() => {
    if (!isHost || !interviewOn) return undefined;
    refreshViolations();
    const timer = setInterval(refreshViolations, 5000);
    return () => clearInterval(timer);
  }, [isHost, interviewOn, refreshViolations]);

  const toggleInterviewMode = useCallback(async () => {
    if (!isHost) return;
    try {
      const updated = await meetingsApi.setInterviewMode(code, !interviewOn);
      setMeeting(updated);
    } catch (cause) {
      setCameraError(cause.message ?? 'Could not change interview mode');
    }
  }, [code, interviewOn, isHost]);

  // --- the call ------------------------------------------------------------
  const {
    remoteStream,
    connectionState,
    peer,
    error: rtcError,
    hangUp,
    replaceVideoTrack,
  } = useWebRTC({
    meetingCode: code,
    localStream,
    enabled: Boolean(localStream && meeting),
  });

  // --- controls ------------------------------------------------------------
  function toggleMic() {
    const next = !micOn;
    // Disabling the track is the right move rather than removing it: the peer
    // connection stays negotiated, so unmuting is instant instead of
    // triggering a fresh offer/answer round trip.
    localStream?.getAudioTracks().forEach((track) => {
      track.enabled = next;
    });
    setMicOn(next);
  }

  /**
   * Turn the camera genuinely on or off.
   *
   * THE BUG THIS FIXES
   * ------------------
   * This used to set `track.enabled = false`, which keeps the hardware open,
   * keeps the indicator light on, and merely transmits black frames. Two
   * things went wrong as a result:
   *
   *   * the tile went black while the camera was still demonstrably running,
   *     so the button said "Turn camera on" about a camera that was on;
   *   * the detection loop early-returned on !cameraOn WITHOUT clearing
   *     `landmarks`, so the last hand skeleton stayed in React state and kept
   *     drawing over the black tile forever. That is exactly the reported
   *     "both tiles black, yet the skeleton is drawn".
   *
   * Off now STOPS the track and releases the device. On re-acquires it and
   * swaps it into the existing peer connection with replaceTrack, so the
   * remote side sees the stream resume without a renegotiation.
   */
  const toggleCamera = useCallback(async () => {
    if (cameraOn) {
      // Clear the overlay FIRST. Otherwise a stale skeleton is visible for the
      // frame or two before React re-renders without it.
      setLandmarks([]);

      localStream?.getVideoTracks().forEach((track) => {
        track.stop();
        localStream.removeTrack(track);
      });
      await replaceVideoTrack(null);
      setCameraOn(false);
      return;
    }

    try {
      const preferences = loadDevicePreferences();
      const fresh = await navigator.mediaDevices.getUserMedia({
        video: preferences?.cameraId
          ? { deviceId: { exact: preferences.cameraId }, width: { ideal: 640 }, height: { ideal: 480 } }
          : { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
        audio: false,
      });

      const [track] = fresh.getVideoTracks();
      if (!track) throw new Error('No video track');

      localStream?.addTrack(track);
      await replaceVideoTrack(track);

      if (localVideoRef.current && localStream) {
        localVideoRef.current.srcObject = localStream;
        await localVideoRef.current.play().catch(() => {});
      }
      setCameraOn(true);
    } catch (cause) {
      setCameraError(
        cause?.name === 'NotAllowedError'
          ? 'Camera permission denied. Allow it in your browser, then try again.'
          : `Could not restart the camera: ${cause?.message ?? cause}`,
      );
    }
  }, [cameraOn, localStream, replaceVideoTrack]);

  async function leaveMeeting() {
    hangUp();
    try {
      await meetingsApi.leave(code);
    } catch {
      // Leaving is best-effort; the user is going regardless.
    }
    navigate('/', { replace: true });
  }


  // Start on a mode the server can actually serve. Defaulting to ASL when only
  // the ISL word model is trained would show an empty panel and look broken,
  // so the first usable mode is selected once the server reports what it has.
  // Word signs are preferred: that is the model a fluent signer will use.
  useEffect(() => {
    const available = {
      dynamic: dynamicModelInfo?.loaded,
      isl: islModelInfo?.loaded,
      static: modelInfo?.loaded,
    };
    if (available[recognitionMode] || Object.values(available).every((v) => v === undefined)) return;
    const usable = ['dynamic', 'isl', 'static'].find((name) => available[name]);
    if (usable) setRecognitionMode(usable);
  }, [modelInfo, islModelInfo, dynamicModelInfo]);

  const handDetected = landmarks.length > 0;

  return (
    <main className="mx-auto flex min-h-screen max-w-7xl flex-col gap-4 p-4">
      {/* The dialog blocks the meeting until acknowledged. Its button is also
          the user gesture the browser requires before fullscreen is allowed —
          which is why enforcement starts on the click, not on mount. */}
      {interviewOn && !isHost && !interview.acknowledged && (
        <InterviewModeDialog
          hostName={meeting?.host?.name}
          capabilities={interview.capabilities}
          onAcknowledge={interview.acknowledge}
        />
      )}

      {/* Covers the meeting while they are away or out of fullscreen, so
          leaving costs them the view rather than being free. */}
      {debugEnabled && (
        <DebugOverlay
          micTrack={localStream?.getAudioTracks()[0]?.readyState ?? 'none'}
          cameraTrack={localStream?.getVideoTracks()[0]?.readyState ?? 'none'}
          speech={{
            engineActive: speech.engineActive,
            state: speech.state,
            lastInterim: speech.lastInterim,
            error: speech.error,
          }}
          sign={signCaptions.debug}
          socketStatus={signSocketStatus}
          lastSent={lastSentRef2.current}
          lastReceived={lastReceivedRef.current}
        />
      )}

      {interview.mustBlock && (
        <InterviewModeOverlay
          awayCount={interview.awayCount}
          maxViolations={MAX_VIOLATIONS}
          isFullscreen={interview.isFullscreen}
          onReturn={interview.reEnterFullscreen}
        />
      )}

      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {meeting?.title ?? 'Meeting'}
          </h1>
          <p className="text-sm text-slate-400">
            Code <span className="font-mono font-semibold text-slate-200">{code}</span>
            {' · '}
            {peer ? `with ${peer.name}` : 'waiting for the other participant'}
            {' · '}
            call {connectionState}
            {meeting?.started_at && (
              <>
                {' · '}
                <MeetingTimer startedAt={meeting.started_at} />
              </>
            )}
          </p>

          <div className="mt-2 flex flex-wrap items-center gap-2">
            <CopyLinkButton code={code} />
            <CaptionSizeControl size={captionSize.size} onChoose={captionSize.choose} />
            {interviewOn && (
              <span
                className="rounded bg-signal-warn/20 px-2 py-1 text-xs font-semibold uppercase text-signal-warn"
                role="status"
              >
                Interview mode
              </span>
            )}
          </div>
        </div>
        <button type="button" onClick={leaveMeeting}
                className="rounded-lg bg-signal-bad px-4 py-2 font-semibold text-ink-900 hover:opacity-90">
          Leave meeting
        </button>
      </header>

      {(cameraError || rtcError || landmarkerError) && (
        <p className="rounded-lg border border-signal-bad/40 bg-signal-bad/10 p-3 text-sm text-signal-bad"
           role="alert">
          {cameraError || rtcError || landmarkerError}
        </p>
      )}

      <div className="grid flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <VideoTile
              videoRef={localVideoRef}
              stream={localStream}
              label={`${user?.name ?? 'You'} (you)`}
              muted
              mirrored
              placeholder={cameraError ?? 'Starting camera…'}
            >
              {signRecognitionOn && (
                <HandOverlayCanvas
                  landmarks={landmarks}
                  mirrored
                  stable={prediction?.stable ?? false}
                />
              )}
            </VideoTile>

            <VideoTile
              stream={remoteStream}
              label={peer?.name ?? 'Waiting for participant'}
              placeholder="Share the meeting code so someone can join."
            />
          </div>

          <CaptionArea
            captions={captions}
            size={captionSize.size}
            visible={captionsVisible}
          />

          {/* --- control bar ------------------------------------------- */}
          {/* Producing captions is automatic and keyed to the microphone and
              camera. These buttons control the DEVICES and the DISPLAY, never
              whether recognition runs — that separation is the whole point of
              Part A1. */}
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-ink-700 bg-ink-800 p-3">
            <button
              type="button"
              onClick={toggleMic}
              aria-pressed={micOn}
              title="Microphone (Ctrl+D). Speech captions follow this."
              className={`rounded-full border px-4 py-2 text-sm ${
                micOn ? 'border-ink-700 hover:bg-ink-700' : 'border-signal-bad bg-signal-bad/20 text-signal-bad'
              }`}
            >
              {micOn ? 'Mute' : 'Unmute'}
            </button>

            <button
              type="button"
              onClick={toggleCamera}
              aria-pressed={cameraOn}
              title="Camera (Ctrl+E)"
              className={`rounded-full border px-4 py-2 text-sm ${
                cameraOn ? 'border-ink-700 hover:bg-ink-700' : 'border-signal-bad bg-signal-bad/20 text-signal-bad'
              }`}
            >
              {cameraOn ? 'Camera off' : 'Camera on'}
            </button>

            <button
              type="button"
              onClick={() => setCaptionsVisible((value) => !value)}
              aria-pressed={captionsVisible}
              title="Show or hide captions (C). Does not affect what others receive."
              className={`rounded-full border px-4 py-2 text-sm ${
                captionsVisible
                  ? 'border-bridge-500 bg-bridge-500/20 text-bridge-400'
                  : 'border-ink-700 hover:bg-ink-700'
              }`}
            >
              CC
            </button>

            <button
              type="button"
              onClick={() => setSignRecognitionOn((value) => !value)}
              aria-pressed={signRecognitionOn}
              disabled={!cameraOn}
              title={cameraOn ? 'Sign recognition' : 'Turn on your camera to sign'}
              className={`rounded-full border px-4 py-2 text-sm disabled:opacity-40 ${
                signRecognitionOn
                  ? 'border-bridge-500 bg-bridge-500/20 text-bridge-400'
                  : 'border-ink-700 hover:bg-ink-700'
              }`}
            >
              🤟 Sign
            </button>

            {isHost && (
              <button
                type="button"
                onClick={toggleInterviewMode}
                aria-pressed={interviewOn}
                className={`rounded-full border px-4 py-2 text-sm ${
                  interviewOn
                    ? 'border-signal-warn bg-signal-warn/20 text-signal-warn'
                    : 'border-ink-700 hover:bg-ink-700'
                }`}
              >
                Interview mode
              </button>
            )}

            <span className="ml-auto text-xs text-slate-400">
              {speech.engineActive
                ? `speech: ${speech.engineActive} · ${speech.state}`
                : 'speech: unavailable in this browser'}
            </span>

            {speech.error && (
              <span className="text-xs text-signal-bad" role="alert">
                {speech.error}
              </span>
            )}
            {speech.notice && (
              <span className="text-xs text-signal-warn">{speech.notice}</span>
            )}
          </div>
        </div>
      </div>

      {landmarkerStatus === 'loading' && (
        <p className="text-sm text-slate-400" role="status">
          Loading hand-tracking model…
        </p>
      )}
    </main>
  );
}
