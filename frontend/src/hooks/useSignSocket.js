import { useCallback, useEffect, useRef, useState } from 'react';

import { buildPredictSocketUrl } from '../services/api';

/**
 * Manages the WebSocket to /ws/predict, with automatic reconnection.
 *
 * WHY THE RECONNECT LOGIC IS WORTH THE COMPLEXITY
 * -----------------------------------------------
 * A laptop that sleeps, a Wi-Fi handover between access points, or the backend
 * restarting during development all drop this socket. Without reconnection the
 * demo silently stops recognising anything, with no error and no clue why —
 * the camera is still on, the skeleton still draws, and nothing appears.
 *
 * Backoff is exponential with jitter. Exponential so a server that is down does
 * not get hammered; jittered so that if several clients drop at once they do
 * not all retry in lockstep and re-create the same stampede.
 */

const INITIAL_RETRY_MS = 500;
const MAX_RETRY_MS = 10_000;
const MAX_ATTEMPTS = 12;

export function useSignSocket({ meetingCode, enabled = true, onSubtitle } = {}) {
  const socketRef = useRef(null);
  const retryTimerRef = useRef(null);
  const attemptRef = useRef(0);
  // Distinguishes a deliberate close (component unmounting, user leaving) from
  // a dropped connection. Without it, unmounting triggers a reconnect to a
  // socket nobody is listening to any more.
  const intentionalCloseRef = useRef(false);

  const [status, setStatus] = useState('idle'); // idle|connecting|open|reconnecting|closed|error
  const [prediction, setPrediction] = useState(null);
  const [sentence, setSentence] = useState('');
  const [serverError, setServerError] = useState(null);
  const [modelInfo, setModelInfo] = useState(null);
  // Model B is a stretch goal and a backend without one is a supported
  // configuration, so the UI has to be told whether the word-sign toggle is
  // worth offering at all rather than assuming it works.
  const [dynamicModelInfo, setDynamicModelInfo] = useState(null);

  // Kept in a ref so a changing callback identity does not tear down and
  // rebuild the socket on every parent render.
  const onSubtitleRef = useRef(onSubtitle);
  useEffect(() => {
    onSubtitleRef.current = onSubtitle;
  }, [onSubtitle]);

  const connect = useCallback(() => {
    if (!meetingCode) return;

    // Guard against opening a second socket over a live one.
    if (
      socketRef.current &&
      (socketRef.current.readyState === WebSocket.OPEN ||
        socketRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    setStatus(attemptRef.current === 0 ? 'connecting' : 'reconnecting');

    const socket = new WebSocket(buildPredictSocketUrl(meetingCode));
    socketRef.current = socket;

    socket.onopen = () => {
      attemptRef.current = 0;
      setStatus('open');
      setServerError(null);
    };

    socket.onmessage = (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }

      switch (message.type) {
        case 'connected':
          setModelInfo(message.model ?? null);
          setDynamicModelInfo(message.dynamic_model ?? null);
          break;

        case 'prediction':
          setPrediction(message);
          setSentence(message.sentence ?? '');
          break;

        case 'sentence':
          setSentence(message.sentence ?? '');
          break;

        case 'subtitle':
          // Text recognised by the *other* participant.
          onSubtitleRef.current?.(message);
          break;

        case 'error':
          setServerError({ code: message.code, message: message.message });
          break;

        case 'pong':
          break;

        default:
          break;
      }
    };

    socket.onerror = () => {
      // The browser deliberately does not say why a WebSocket failed, to avoid
      // leaking cross-origin information. onclose carries the useful code.
      setStatus('error');
    };

    socket.onclose = (event) => {
      socketRef.current = null;

      if (intentionalCloseRef.current) {
        setStatus('closed');
        return;
      }

      // 1008 is our policy-violation code: a bad token or a meeting that does
      // not exist. Retrying cannot fix either, so stop and say so.
      if (event.code === 1008) {
        setStatus('error');
        setServerError({
          code: 'UNAUTHORIZED',
          message: event.reason || 'Not authorised for this meeting. Try logging in again.',
        });
        return;
      }

      if (attemptRef.current >= MAX_ATTEMPTS) {
        setStatus('closed');
        setServerError({
          code: 'RECONNECT_FAILED',
          message: `Gave up after ${MAX_ATTEMPTS} attempts. Is the backend running?`,
        });
        return;
      }

      const delay = Math.min(INITIAL_RETRY_MS * 2 ** attemptRef.current, MAX_RETRY_MS);
      // Up to 30% jitter, so simultaneous drops do not retry in lockstep.
      const jittered = delay * (0.85 + Math.random() * 0.3);
      attemptRef.current += 1;

      setStatus('reconnecting');
      retryTimerRef.current = setTimeout(connect, jittered);
    };
  }, [meetingCode]);

  useEffect(() => {
    if (!enabled || !meetingCode) return undefined;

    intentionalCloseRef.current = false;
    attemptRef.current = 0;
    connect();

    return () => {
      intentionalCloseRef.current = true;
      clearTimeout(retryTimerRef.current);
      socketRef.current?.close();
      socketRef.current = null;
      setStatus('idle');
    };
  }, [connect, enabled, meetingCode]);

  /** Send one frame of landmarks. Silently no-ops if the socket is not open. */
  const sendLandmarks = useCallback((hands, mode = 'static') => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;

    // bufferedAmount guards against a slow network: if frames are queuing up
    // faster than they drain, dropping the newest is far better than building
    // an ever-growing backlog that makes predictions arrive seconds late.
    if (socket.bufferedAmount > 64 * 1024) return false;

    socket.send(
      JSON.stringify({ type: 'landmarks', mode, timestamp: Date.now(), hands }),
    );
    return true;
  }, []);

  /**
   * Relay recognised speech to the other participant.
   *
   * Speech travels on this socket rather than the signalling one because this
   * is the meeting's *text* channel — both translation directions belong
   * together, and a dropped video call must not take the captions down too.
   */
  const sendSpeech = useCallback((text, isFinal) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN || !text) return false;

    socket.send(JSON.stringify({ type: 'speech', text, is_final: Boolean(isFinal) }));
    return true;
  }, []);

  const sendControl = useCallback((type) => {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type }));
  }, []);

  const clearSentence = useCallback(() => sendControl('clear'), [sendControl]);
  const backspace = useCallback(() => sendControl('backspace'), [sendControl]);

  return {
    status,
    prediction,
    sentence,
    serverError,
    modelInfo,
    dynamicModelInfo,
    sendLandmarks,
    sendSpeech,
    clearSentence,
    backspace,
    isConnected: status === 'open',
  };
}
