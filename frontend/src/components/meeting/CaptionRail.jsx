import { useEffect, useRef } from 'react';

import Avatar from '../ui/Avatar';
import Icon from '../ui/Icon';

/**
 * The live caption area, between the stage and the control bar.
 *
 * WHY ENTRIES ARE KEYED BY SEGMENT ID
 * -----------------------------------
 * Each interim event carries the FULL current text of its segment, and the
 * store replaces that entry in place. Keying React's list on the segment id is
 * what makes the line update rather than a new line appearing underneath the
 * old one. The reported
 * "BBBD location location warm warm fast we we we we old warm warm warm"
 * was every interim being rendered as its own caption.
 *
 * Shows the most recent three lines. Older ones scroll up and out; the complete
 * record is in the transcript, which reads from the database rather than from
 * this list.
 *
 * INTERIM IS GREY, FINAL IS WHITE
 * -------------------------------
 * This is the only signal a reader gets that text may still change. Without it,
 * a deaf participant cannot tell a settled sentence from a guess the recogniser
 * is about to revise, and revisions look like the system contradicting itself.
 */

const SIZE_CLASS = {
  normal: 'text-caption',
  large: 'text-caption-lg',
  xlarge: 'text-caption-xl',
};

const VISIBLE_LINES = 3;

export default function CaptionRail({ captions, size = 'normal', visible = true }) {
  const scrollRef = useRef(null);

  // Keep the newest line in view. This runs on every interim — several times a
  // second — so `scrollTop` is assigned directly. `scrollIntoView({behavior:
  // 'smooth'})` would queue animations faster than they can finish and the rail
  // would visibly lag behind the text.
  useEffect(() => {
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [captions]);

  // Hidden entirely rather than visually: the stage reclaims the 140px.
  if (!visible) return null;

  const textClass = SIZE_CLASS[size] ?? SIZE_CLASS.normal;
  const recent = captions.slice(-VISIBLE_LINES);

  return (
    <section
      aria-label="Live captions"
      className="h-captions shrink-0 border-t border-dark-surface bg-dark-bg"
    >
      <div
        ref={scrollRef}
        // aria-live so a screen-reader user hears captions as they settle.
        // "polite" deliberately: "assertive" would cut off the previous line
        // mid-word every time an interim arrived.
        aria-live="polite"
        aria-atomic="false"
        className="mx-auto flex h-full max-w-caption flex-col justify-end gap-2 overflow-y-auto px-4 py-3"
      >
        {recent.length === 0 ? (
          <p className="text-sm text-dark-muted">
            Captions will appear here as people sign or speak.
          </p>
        ) : (
          recent.map((caption) => (
            <article key={caption.segmentId} className="animate-fade-in">
              <div className="flex items-center gap-2">
                <Avatar name={caption.speakerName} size={20} />
                <span className="truncate text-xs font-medium text-dark-muted">
                  {caption.speakerName}
                </span>
                <SourceBadge source={caption.source} />
              </div>
              <p
                className={`mt-0.5 break-words font-medium transition-colors ${textClass}
                            ${caption.isFinal ? 'text-white' : 'text-[#BDC1C6]'}`}
              >
                {caption.text}
              </p>
            </article>
          ))
        )}
      </div>
    </section>
  );
}

function SourceBadge({ source }) {
  const isSign = source === 'sign';
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 rounded-full bg-white/10 px-1.5
                 py-0.5 text-[10px] font-medium uppercase tracking-wide text-dark-muted"
    >
      <Icon name={isSign ? 'sign_language' : 'mic'} size={12} />
      {isSign ? 'Sign' : 'Speech'}
    </span>
  );
}
