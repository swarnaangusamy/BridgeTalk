import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import HandOverlayCanvas from '../components/HandOverlayCanvas';
import ModeSwitch from '../components/ModeSwitch';
import SignDetectionPanel from '../components/SignDetectionPanel';
import SubtitleBar from '../components/SubtitleBar';
import TranscriptPanel from '../components/TranscriptPanel';
import VideoTile from '../components/VideoTile';
import { useAuth } from '../context/AuthContext';
import { useFocusMonitor } from '../hooks/useFocusMonitor';
import { useHandLandmarker } from '../hooks/useHandLandmarker';
import { useSignSocket } from '../hooks/useSignSocket';
import { useSpeechToText } from '../hooks/useSpeechToText';
import { useWebRTC } from '../hooks/useWebRTC';
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

export default function MeetingRoom() {
  const { code } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();

  const localVideoRef = useRef(null);
  const rafRef = useRef(null);
  const lastSentRef = useRef(0);

  const [meeting, setMeeting] = useState(null);
  const [localStream, setLocalStream] = useState(null);
  const [cameraError, setCameraError] = useState(null);
  const [landmarks, setLandmarks] = useState([]);

  const [signDetectionOn, setSignDetectionOn] = useState(true);
  const [micOn, setMicOn] = useState(true);
  const [cameraOn, setCameraOn] = useState(true);
  const [speechOn, setSpeechOn] = useState(false);
  const [transcriptCollapsed, setTranscriptCollapsed] = useState(false);

  const [subtitle, setSubtitle] = useState(null);
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
        stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
          audio: true,
        });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
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

  // --- translation: sign -> text -------------------------------------------
  const handleIncomingSubtitle = useCallback((message) => {
    setSubtitle({
      text: message.text,
      speaker: message.from?.name ?? 'Participant',
      source: message.source,
      isFinal: message.is_final !== false,
    });

    // Only final lines join the permanent record. Interim speech is revised
    // word by word, so persisting it would fill the transcript with fragments.
    if (message.source === 'speech' && message.is_final === false) return;

    setTranscriptLines((current) => [
      ...current,
      {
        id: `remote-${Date.now()}-${Math.random()}`,
        speaker: message.from?.name ?? 'Participant',
        source: message.source,
        text: message.text,
        confidence: message.confidence ?? null,
        timestamp: new Date().toISOString(),
      },
    ]);
  }, []);

  const {
    status: signSocketStatus,
    prediction,
    sentence,
    serverError: signError,
    modelInfo,
    sendLandmarks,
    sendSpeech,
    clearSentence,
    backspace,
  } = useSignSocket({
    meetingCode: code,
    enabled: Boolean(meeting),
    onSubtitle: handleIncomingSubtitle,
  });

  const { detect, status: landmarkerStatus, error: landmarkerError, isReady } =
    useHandLandmarker({ numHands: 1, enabled: signDetectionOn });

  useEffect(() => {
    if (!localStream || !isReady || !signDetectionOn || !cameraOn) return undefined;

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
          sendLandmarks(toWireFormat(result), 'static');
        }
      } else {
        setLandmarks([]);
        if (shouldSend) {
          lastSentRef.current = now;
          // Empty frames matter: they drive the neutral reset that closes a
          // word when the signer lowers their hand.
          sendLandmarks([], 'static');
        }
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      active = false;
      cancelAnimationFrame(rafRef.current);
    };
  }, [localStream, isReady, signDetectionOn, cameraOn, detect, sendLandmarks]);

  // Show each accepted letter locally, and persist completed WORDS.
  //
  // Persisting per letter would write a database row for every character and
  // produce a transcript that reads "H", "E", "L", "L", "O" — technically
  // accurate and completely useless to read back. The word boundary (a `space`
  // being emitted) is the natural unit, and it matches how the speech side
  // persists whole final phrases rather than partial ones.
  const lastEmittedRef = useRef(null);
  const persistedUpToRef = useRef(0);

  useEffect(() => {
    if (!prediction?.emitted || !meeting) return;

    // React can re-run this for the same prediction object; the signature
    // makes the effect idempotent.
    const signature = `${prediction.emitted}-${prediction.sentence}`;
    if (lastEmittedRef.current === signature) return;
    lastEmittedRef.current = signature;

    setSubtitle({
      text: prediction.sentence,
      speaker: user?.name ?? 'You',
      source: 'sign',
      isFinal: true,
    });

    if (prediction.emitted !== 'space') return;

    const completed = prediction.sentence.slice(persistedUpToRef.current).trim();
    persistedUpToRef.current = prediction.sentence.length;
    if (!completed) return;

    setTranscriptLines((current) => [
      ...current,
      {
        id: `local-sign-${Date.now()}`,
        speaker: user?.name ?? 'You',
        source: 'sign',
        text: completed,
        confidence: prediction.confidence ?? null,
        timestamp: new Date().toISOString(),
      },
    ]);

    transcriptsApi
      .append({
        meetingId: meeting.id,
        source: 'sign',
        content: completed,
        confidence: prediction.confidence ?? null,
      })
      .catch(() => {
        // A failed write must not interrupt the conversation — the word is
        // already on screen, which is what the participants actually need.
      });
  }, [prediction, meeting, user]);

  // --- translation: speech -> text -----------------------------------------
  const handleSpeechResult = useCallback(
    ({ text, isFinal, confidence }) => {
      if (!text) return;

      // Relay to the other participant through the inference socket, which is
      // the meeting's text channel for both translation directions. Interim
      // results are sent too, so their caption updates word by word rather
      // than appearing in silent bursts at the end of each sentence.
      sendSpeech(text, isFinal);

      setSubtitle({ text, speaker: user?.name ?? 'You', source: 'speech', isFinal });

      if (!isFinal || !meeting) return;

      setTranscriptLines((current) => [
        ...current,
        {
          id: `local-speech-${Date.now()}`,
          speaker: user?.name ?? 'You',
          source: 'speech',
          text,
          confidence: null,
          timestamp: new Date().toISOString(),
        },
      ]);

      transcriptsApi
        .append({ meetingId: meeting.id, source: 'speech', content: text })
        .catch(() => {
          // A failed persist must not break the live caption — the words are
          // already on screen, which is what the conversation needs.
        });
    },
    [meeting, user, sendSpeech],
  );

  const speech = useSpeechToText({
    enabled: speechOn,
    onResult: handleSpeechResult,
  });

  useEffect(() => {
    if (speechOn) speech.start();
    else speech.stop();
  }, [speechOn, speech]);

  // --- Interview Mode ------------------------------------------------------
  // Enabled per meeting, chosen by the host at creation time. Each focus
  // change is posted to the backend so the record survives a page reload —
  // a tab switch the participant then refreshes away should still be there.
  const handleFocusEvent = useCallback(
    (eventType) => {
      if (!meeting?.is_interview_mode) return;
      meetingsApi.logFocusEvent(code, eventType).catch(() => {
        // Best effort. A failed log must never interrupt the meeting itself.
      });
    },
    [code, meeting],
  );

  const focus = useFocusMonitor({
    enabled: Boolean(meeting?.is_interview_mode),
    onEvent: handleFocusEvent,
  });

  // --- the call ------------------------------------------------------------
  const { remoteStream, connectionState, peer, error: rtcError, hangUp } = useWebRTC({
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

  function toggleCamera() {
    const next = !cameraOn;
    localStream?.getVideoTracks().forEach((track) => {
      track.enabled = next;
    });
    setCameraOn(next);
  }

  async function leaveMeeting() {
    hangUp();
    try {
      await meetingsApi.leave(code);
    } catch {
      // Leaving is best-effort; the user is going regardless.
    }
    navigate('/', { replace: true });
  }

  const handDetected = landmarks.length > 0;

  return (
    <main className="mx-auto flex min-h-screen max-w-7xl flex-col gap-4 p-4">
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
          </p>
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
              {signDetectionOn && (
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

          <SubtitleBar subtitle={subtitle} />

          {/* --- control bar ------------------------------------------- */}
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-ink-700 bg-ink-800 p-3">
            <button type="button" onClick={toggleMic} aria-pressed={micOn}
                    className="rounded-lg border border-ink-700 px-3 py-2 text-sm hover:bg-ink-700">
              {micOn ? 'Mute mic' : 'Unmute mic'}
            </button>
            <button type="button" onClick={toggleCamera} aria-pressed={cameraOn}
                    className="rounded-lg border border-ink-700 px-3 py-2 text-sm hover:bg-ink-700">
              {cameraOn ? 'Turn camera off' : 'Turn camera on'}
            </button>
            <button type="button" onClick={() => setSignDetectionOn((v) => !v)}
                    aria-pressed={signDetectionOn}
                    className="rounded-lg border border-ink-700 px-3 py-2 text-sm hover:bg-ink-700">
              Sign detection: {signDetectionOn ? 'on' : 'off'}
            </button>
            <button type="button" onClick={() => setSpeechOn((v) => !v)}
                    aria-pressed={speechOn} disabled={!speech.isSupported}
                    title={speech.isSupported ? undefined : 'Your browser does not support the Web Speech API'}
                    className="rounded-lg border border-ink-700 px-3 py-2 text-sm hover:bg-ink-700 disabled:opacity-50">
              Speech captions: {speechOn ? 'on' : 'off'}
            </button>

            {!speech.isSupported && (
              <span className="text-xs text-slate-400">
                Speech captions need Chrome or Edge.
              </span>
            )}
            {speech.error && (
              <span className="text-xs text-signal-bad">{speech.error}</span>
            )}
          </div>
        </div>

        {/* --- right column ---------------------------------------------- */}
        <aside className="flex flex-col gap-4">
          <ModeSwitch
            enabled={Boolean(meeting?.is_interview_mode)}
            awayCount={focus.awayCount}
            isAway={focus.isAway}
          />

          <SignDetectionPanel
            status={signSocketStatus}
            prediction={prediction}
            sentence={sentence}
            serverError={signError}
            modelInfo={modelInfo}
            handDetected={handDetected}
            onClear={clearSentence}
            onBackspace={backspace}
          />

          <div className="min-h-[18rem] flex-1">
            <TranscriptPanel
              lines={transcriptLines}
              meetingId={meeting?.id}
              collapsed={transcriptCollapsed}
              onToggle={() => setTranscriptCollapsed((v) => !v)}
            />
          </div>
        </aside>
      </div>

      {landmarkerStatus === 'loading' && (
        <p className="text-sm text-slate-400" role="status">
          Loading hand-tracking model…
        </p>
      )}
    </main>
  );
}
