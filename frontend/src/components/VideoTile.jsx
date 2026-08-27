import { useEffect, useRef } from 'react';

/**
 * One participant's video, with an optional overlay (the landmark skeleton).
 *
 * `srcObject` cannot be set through a React prop — it takes a MediaStream
 * object, not a URL string — so it is assigned imperatively through a ref.
 * This is one of the genuine cases where reaching for the DOM is correct
 * rather than a shortcut.
 */
export default function VideoTile({
  stream,
  label,
  muted = false,
  mirrored = false,
  placeholder = 'Waiting…',
  children,
  videoRef: externalRef,
}) {
  const internalRef = useRef(null);
  const videoRef = externalRef ?? internalRef;

  useEffect(() => {
    const element = videoRef.current;
    if (!element) return;

    if (element.srcObject !== stream) {
      element.srcObject = stream ?? null;
    }
  }, [stream, videoRef]);

  return (
    <figure className="relative aspect-video overflow-hidden rounded-xl border border-ink-700 bg-ink-900">
      <video
        ref={videoRef}
        autoPlay
        playsInline
        // The local tile MUST be muted, or the microphone feeds back into the
        // speakers and howls. Only the remote tile plays audio.
        muted={muted}
        className={`h-full w-full object-cover ${mirrored ? '-scale-x-100' : ''}`}
      />

      {/* Overlays (e.g. the hand skeleton canvas) render on top of the video. */}
      {children}

      {!stream && (
        <p className="absolute inset-0 grid place-items-center px-4 text-center text-slate-400">
          {placeholder}
        </p>
      )}

      <figcaption className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-ink-900/90 to-transparent px-3 py-2 text-sm font-medium text-slate-100">
        {label}
      </figcaption>
    </figure>
  );
}
