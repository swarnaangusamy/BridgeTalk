import { useCallback, useEffect, useRef, useState } from 'react';

import { getToken, WS_BASE_URL } from '../services/api';

/**
 * Establishes a 1:1 WebRTC call, using our backend purely as a signalling relay.
 *
 * THE SEQUENCE
 * ------------
 *   1. Both peers open /ws/signal/{code}.
 *   2. The server tells the *second* arrival `should_initiate: true`. Exactly
 *      one side must offer — if both do, the negotiations collide ("glare")
 *      and both have to back off and retry.
 *   3. Initiator: createOffer -> setLocalDescription -> send through the relay.
 *   4. Responder: setRemoteDescription -> createAnswer -> send back.
 *   5. Both: trickle ICE candidates to each other as they are discovered.
 *   6. The peers connect directly. Audio and video never touch our server.
 *
 * WHAT CAN GO WRONG, HONESTLY
 * ---------------------------
 * We configure STUN but no TURN. STUN lets a browser discover its own public
 * address; TURN relays the media when a direct path is impossible, which
 * happens behind symmetric NAT or a restrictive corporate firewall. Without
 * TURN those calls simply fail to connect. Two tabs on one laptop, or two
 * laptops on one Wi-Fi network, connect fine — and that is what the demo uses.
 */

/**
 * ICE servers, configured from the environment so a TURN server can be added
 * at deployment without touching this file.
 *
 *   VITE_STUN_URLS   comma-separated, e.g. "stun:stun.l.google.com:19302,stun:..."
 *   VITE_TURN_URLS   comma-separated, e.g. "turn:turn.example.org:3478"
 *   VITE_TURN_USERNAME / VITE_TURN_CREDENTIAL
 *
 * WHY TURN MATTERS AND STUN IS NOT ENOUGH
 * ---------------------------------------
 * STUN only tells each peer what its own public address looks like. That is
 * sufficient when the two peers can reach each other directly, which is the
 * case for two laptops on one Wi-Fi network — the demo setup. It fails on
 * symmetric NAT and on many corporate and mobile networks, where the only way
 * through is to relay the media through a TURN server.
 *
 * No TURN server is configured by default because running one costs bandwidth
 * and this is a locally-demonstrated project. The hooks are here so that
 * deploying behind a TURN server is a .env change rather than a code change.
 */
function parseUrls(value) {
  return (value ?? '')
    .split(',')
    .map((url) => url.trim())
    .filter(Boolean);
}

const STUN_URLS = parseUrls(
  import.meta.env.VITE_STUN_URLS ??
    'stun:stun.l.google.com:19302,stun:stun1.l.google.com:19302',
);
const TURN_URLS = parseUrls(import.meta.env.VITE_TURN_URLS);

const ICE_SERVERS = [
  // Several STUN servers are listed because any one of them may be
  // unreachable from a given network, and ICE uses whichever responds.
  ...(STUN_URLS.length ? [{ urls: STUN_URLS }] : []),
  ...(TURN_URLS.length
    ? [
        {
          urls: TURN_URLS,
          username: import.meta.env.VITE_TURN_USERNAME,
          credential: import.meta.env.VITE_TURN_CREDENTIAL,
        },
      ]
    : []),
];

export function useWebRTC({ meetingCode, localStream, enabled = true }) {
  const peerRef = useRef(null);

  /**
   * Swap the outgoing video track without renegotiating.
   *
   * Needed because turning the camera off now genuinely STOPS the track
   * rather than just disabling it — `enabled = false` keeps the hardware open
   * and the indicator light on, which is not "off" in any sense a user means.
   *
   * replaceTrack is the right tool: it changes what the existing sender
   * transmits, so there is no new offer/answer round trip and the remote peer
   * sees the stream continue rather than drop and restart.
   *
   * Passing null makes the sender transmit nothing, which is what the remote
   * side should see while the camera is released.
   */
  const replaceVideoTrack = useCallback(async (track) => {
    const connection = peerRef.current;
    if (!connection) return false;

    const sender = connection.getSenders().find((s) => s.track?.kind === 'video')
      ?? connection.getSenders().find((s) => s.track === null);
    if (!sender) return false;

    try {
      await sender.replaceTrack(track ?? null);
      return true;
    } catch {
      // Older browsers, or a sender in a state that refuses the swap. The
      // local camera state is still correct; only the remote view is stale.
      return false;
    }
  }, []);
  const socketRef = useRef(null);
  // ICE candidates can arrive before the remote description is set, and
  // addIceCandidate throws if it does. They are queued here and flushed once
  // the description lands.
  const pendingCandidatesRef = useRef([]);
  const intentionalCloseRef = useRef(false);

  const [remoteStream, setRemoteStream] = useState(null);
  const [connectionState, setConnectionState] = useState('new');
  const [peer, setPeer] = useState(null);
  const [signalStatus, setSignalStatus] = useState('idle');
  const [error, setError] = useState(null);

  const send = useCallback((message) => {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
  }, []);

  /** Build the RTCPeerConnection and wire up its events. */
  const createPeerConnection = useCallback(() => {
    if (peerRef.current) return peerRef.current;

    const connection = new RTCPeerConnection({ iceServers: ICE_SERVERS });

    // Publish our own audio/video tracks onto the connection.
    if (localStream) {
      for (const track of localStream.getTracks()) {
        connection.addTrack(track, localStream);
      }
    }

    connection.ontrack = (event) => {
      // event.streams[0] is the remote MediaStream. Setting it in state hands
      // it to the <video> element for the other participant's tile.
      setRemoteStream(event.streams[0] ?? null);
    };

    connection.onicecandidate = (event) => {
      // A null candidate means gathering has finished — nothing to relay.
      if (event.candidate) {
        send({ type: 'ice-candidate', payload: event.candidate.toJSON() });
      }
    };

    connection.onconnectionstatechange = () => {
      setConnectionState(connection.connectionState);
      if (connection.connectionState === 'failed') {
        setError(
          'Could not establish a direct connection. This usually means both ' +
            'peers are behind restrictive NATs, which needs a TURN server we ' +
            'do not run. Try two tabs on one machine, or two devices on the ' +
            'same Wi-Fi network.',
        );
      }
    };

    peerRef.current = connection;
    return connection;
  }, [localStream, send]);

  const flushPendingCandidates = useCallback(async (connection) => {
    for (const candidate of pendingCandidatesRef.current) {
      try {
        await connection.addIceCandidate(candidate);
      } catch (cause) {
        console.warn('Failed to add a queued ICE candidate', cause);
      }
    }
    pendingCandidatesRef.current = [];
  }, []);

  const startCall = useCallback(async () => {
    const connection = createPeerConnection();
    const offer = await connection.createOffer();
    await connection.setLocalDescription(offer);
    send({ type: 'offer', payload: offer });
  }, [createPeerConnection, send]);

  // --- signalling socket ---------------------------------------------------
  useEffect(() => {
    if (!enabled || !meetingCode || !localStream) return undefined;

    intentionalCloseRef.current = false;
    const url = `${WS_BASE_URL}/ws/signal/${encodeURIComponent(meetingCode)}?token=${encodeURIComponent(getToken() ?? '')}`;
    const socket = new WebSocket(url);
    socketRef.current = socket;
    setSignalStatus('connecting');

    socket.onopen = () => setSignalStatus('open');

    socket.onmessage = async (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }

      const connection = peerRef.current ?? createPeerConnection();

      switch (message.type) {
        case 'joined':
          setPeer(message.peers?.[0] ?? null);
          // The second arrival initiates — it is the one that knows somebody
          // is already waiting.
          if (message.should_initiate) await startCall();
          break;

        case 'peer-joined':
          setPeer(message.peer);
          break;

        case 'peer-left':
          setPeer(null);
          setRemoteStream(null);
          break;

        case 'offer': {
          await connection.setRemoteDescription(new RTCSessionDescription(message.payload));
          await flushPendingCandidates(connection);
          const answer = await connection.createAnswer();
          await connection.setLocalDescription(answer);
          send({ type: 'answer', payload: answer });
          break;
        }

        case 'answer':
          await connection.setRemoteDescription(new RTCSessionDescription(message.payload));
          await flushPendingCandidates(connection);
          break;

        case 'ice-candidate': {
          const candidate = new RTCIceCandidate(message.payload);
          if (connection.remoteDescription) {
            try {
              await connection.addIceCandidate(candidate);
            } catch (cause) {
              console.warn('addIceCandidate failed', cause);
            }
          } else {
            // Trickle ICE means candidates routinely arrive before the
            // description. Queue rather than drop them — a dropped candidate
            // can be the one viable network path.
            pendingCandidatesRef.current.push(candidate);
          }
          break;
        }

        case 'hangup':
          setPeer(null);
          setRemoteStream(null);
          peerRef.current?.close();
          peerRef.current = null;
          break;

        case 'error':
          setError(message.message);
          break;

        default:
          break;
      }
    };

    socket.onclose = () => {
      setSignalStatus(intentionalCloseRef.current ? 'closed' : 'disconnected');
    };

    return () => {
      intentionalCloseRef.current = true;
      socket.close();
      socketRef.current = null;
      peerRef.current?.close();
      peerRef.current = null;
      pendingCandidatesRef.current = [];
      setRemoteStream(null);
      setPeer(null);
    };
  }, [enabled, meetingCode, localStream, createPeerConnection, startCall, flushPendingCandidates, send]);

  const hangUp = useCallback(() => {
    send({ type: 'hangup', payload: null });
    peerRef.current?.close();
    peerRef.current = null;
    setRemoteStream(null);
    setPeer(null);
  }, [send]);

  return {
    remoteStream,
    connectionState,
    peer,
    signalStatus,
    error,
    hangUp,
    isConnected: connectionState === 'connected',
    replaceVideoTrack,
  };
}
