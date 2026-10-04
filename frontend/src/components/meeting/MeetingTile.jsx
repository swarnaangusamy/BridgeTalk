import { useEffect, useRef } from 'react';

import Avatar from '../ui/Avatar';
import Icon from '../ui/Icon';

/**
 * One participant's video tile.
 *
 * WHY srcObject IS SET IN AN EFFECT AND NOT AS A PROP
 * --------------------------------------------------
 * `srcObject` takes a MediaStream object, and React can only set DOM
 * *attributes* declaratively — `<video srcObject={stream}>` is silently
 * ignored. It has to be assigned to the element.
 *
 * The identity check before assigning matters too: re-assigning the same stream
 * restarts playback, which shows a black frame. Without it, every parent
 * re-render — and captions cause several a second — would flicker the video.
 *
 * MIRRORING IS LOCAL-ONLY
 * -----------------------
 * Your own tile is mirrored because that is what a mirror shows you and an
 * unmirrored self-view feels wrong. The remote tile must NOT be mirrored: the
 * other person's signs would be flipped, which for a handed language is not a
 * cosmetic difference — it can change which sign is being read.
 */
export default function MeetingTile({
  stream,
  name,
  isLocal = false,
  muted = false,
  cameraOff = false,
  speaking = false,
  signing = false,
  floating = false,
  label,
  children,
  className = '',
}) {
  const videoRef = useRef(null);

  useEffect(() => {
    const element = videoRef.current;
    if (!element) return;
    if (element.srcObject !== (stream ?? null)) {
      element.srcObject = stream ?? null;
    }
  }, [stream]);

  const showVideo = Boolean(stream) && !cameraOff;

  return (
    <div
      className={`group relative overflow-hidden rounded-tile bg-dark-surface
                  ${floating ? 'shadow-tile ring-1 ring-black/40' : ''}
                  ${speaking || signing ? 'ring-2 ring-dark-accent' : ''}
                  ${className}`}
    >
      <video
        ref={videoRef}
        autoPlay
        playsInline
        // Own tile muted, always: unmuted it is a feedback loop through the
        // speakers. The remote tile carries the other person's audio.
        muted={isLocal}
        className={`h-full w-full object-cover ${isLocal ? 'scale-x-[-1]' : ''}
                    ${showVideo ? 'opacity-100' : 'opacity-0'}`}
      />

      {/* Camera off: the specification's #3C4043 tile with a large initial. */}
      {!showVideo ? (
        <div className="absolute inset-0 grid place-items-center bg-dark-surface">
          <Avatar name={name} size={floating ? 48 : 88} />
        </div>
      ) : null}

      {/* Anything the owner wants on top: the landmark overlay, the detection
          pill. Rendered under the name so the gradient stays readable. */}
      {children}

      {/* Name over a subtle gradient, bottom-left. The gradient rather than a
          solid chip because a name must stay legible over both a bright
          window and a dark room. */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/60 to-transparent pt-8">
        <div className="flex items-center gap-1.5 px-3 pb-2">
          {signing ? (
            <Icon
              name="sign_language"
              size={16}
              className="shrink-0 text-dark-accent"
            />
          ) : null}
          <span className={`min-w-0 truncate text-dark-text ${floating ? 'text-xs' : 'text-sm'}`}>
            {label ?? name}
          </span>
        </div>
      </div>

      {/* Muted microphone, top-right. */}
      {muted ? (
        <span
          aria-label={`${name} is muted`}
          className="absolute right-2 top-2 grid h-7 w-7 place-items-center rounded-full bg-black/55 text-dark-text"
        >
          <Icon name="mic_off" size={16} />
        </span>
      ) : null}
    </div>
  );
}
