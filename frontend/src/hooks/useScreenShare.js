import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Screen sharing: an ADDITIONAL track, never a replacement.
 *
 * WHY IT MUST BE ADDITIONAL
 * -------------------------
 * The obvious implementation is replaceTrack on the camera sender — it needs
 * no renegotiation and every tutorial shows it. It is wrong for this project:
 * replacing the camera would hide the signer the moment anyone presents, which
 * removes the one thing BridgeTalk exists to carry. So the screen is added
 * alongside, and the connection renegotiates.
 *
 * THREE WAYS A SHARE ENDS, AND ALL THREE MUST WORK
 * ------------------------------------------------
 *   1. The Stop presenting button.
 *   2. The browser's own "Stop sharing" bar — which does NOT call our code, so
 *      the track's `ended` event is the only way to learn about it. Miss this
 *      and the UI claims someone is presenting a screen that is gone.
 *   3. The presenter leaving, handled by the cleanup on unmount.
 *
 * Cancelling the picker is not an error. getDisplayMedia rejects with
 * NotAllowedError whether the user denied permission or simply pressed Escape,
 * and treating the second as a failure would show an error for a deliberate
 * choice.
 */
export function useScreenShare({
  addScreenTrack,
  removeScreenSender,
  sendSignal,
  onPresentingChange,
} = {}) {
  const [isPresenting, setIsPresenting] = useState(false);
  const [error, setError] = useState(null);

  const streamRef = useRef(null);
  const senderRef = useRef(null);
  const onChangeRef = useRef(onPresentingChange);

  useEffect(() => {
    onChangeRef.current = onPresentingChange;
  }, [onPresentingChange]);

  const stop = useCallback(
    (announce = true) => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;

      if (senderRef.current) {
        removeScreenSender?.(senderRef.current);
        senderRef.current = null;
      }

      if (announce) sendSignal?.({ type: 'presentation-stop', payload: {} });

      setIsPresenting(false);
      onChangeRef.current?.(false);
    },
    [removeScreenSender, sendSignal],
  );

  const start = useCallback(async () => {
    setError(null);

    if (!navigator.mediaDevices?.getDisplayMedia) {
      setError('This browser cannot share a screen.');
      return false;
    }

    let stream;
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        // Screen audio is deliberately not requested. It would be picked up by
        // the speech recogniser and captioned as if the presenter had said it.
        audio: false,
      });
    } catch (cause) {
      // Cancelling the picker rejects with NotAllowedError, exactly as a
      // denial does. There is no way to tell them apart, and showing an error
      // for "changed my mind" is worse than showing nothing.
      if (cause?.name !== 'NotAllowedError') {
        setError(`Could not start sharing: ${cause?.message ?? cause}`);
      }
      return false;
    }

    const [track] = stream.getVideoTracks();
    if (!track) {
      stream.getTracks().forEach((t) => t.stop());
      return false;
    }

    // The browser's own "Stop sharing" bar does not call back into our code.
    // This event is the only notification, and without it the UI would keep
    // claiming a share that has already ended.
    track.addEventListener('ended', () => stop(true));

    streamRef.current = stream;
    senderRef.current = addScreenTrack?.(track, stream) ?? null;

    // Announce BEFORE the track arrives, so the receiver knows which stream id
    // is the screen and can route it rather than guessing from arrival order.
    sendSignal?.({ type: 'presentation-start', payload: { stream_id: stream.id } });

    setIsPresenting(true);
    onChangeRef.current?.(true);
    return true;
  }, [addScreenTrack, sendSignal, stop]);

  // Leaving the meeting mid-share must release the screen.
  useEffect(
    () => () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    },
    [],
  );

  return {
    isPresenting,
    error,
    localScreenStream: streamRef.current,
    startPresenting: start,
    stopPresenting: () => stop(true),
  };
}
