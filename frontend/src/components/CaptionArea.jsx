import { useEffect, useRef } from 'react';

/**
 * The live caption strip, between the stage and the control bar.
 *
 * WHY ENTRIES ARE KEYED BY SEGMENT ID
 * -----------------------------------
 * Each interim event carries the full current text of its segment, and React
 * replaces that entry in place. Keying on the segment id is what makes the
 * line update rather than a new line appearing beneath the old one — the
 * reported "warm warm fast we we we we" was every interim being rendered as
 * its own caption.
 *
 * Shows the most recent few lines. Older ones scroll up and out; the complete
 * record lives in the transcript, which reads from the database.
 */

const SIZE_CLASS = {
  normal: 'text-[22px] leading-snug',
  large: 'text-[28px] leading-snug',
  xlarge: 'text-[34px] leading-snug',
};

export default function CaptionArea({ captions, size = 'normal', visible = true }) {
  const scrollRef = useRef(null);

  // Keep the newest line in view. Captions arrive several times a second, so
  // this runs on every interim; `behavior: smooth` would queue animations
  // faster than they finish.
  useEffect(() => {
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [captions]);

  // Hidden entirely, not just visually: the stage reclaims the space.
  if (!visible) return null;

  const textClass = SIZE_CLASS[size] ?? SIZE_CLASS.normal;

  return (
    <section
      className="h-[140px] shrink-0 overflow-hidden border-t border-[#3C4043] bg-[#202124] px-4"
      aria-label="Live captions"
    >
      <div
        ref={scrollRef}
        className="mx-auto h-full max-w-[900px] overflow-y-auto py-3"
        // polite, not assertive: new captions must be announced without
        // cutting off whatever the screen reader is already saying.
        aria-live="polite"
        aria-atomic="false"
      >
        {captions.length === 0 ? (
          <p className="text-sm text-[#9AA0A6]">
            Captions appear here as either participant signs or speaks.
          </p>
        ) : (
          <ol className="space-y-2">
            {captions.slice(-6).map((caption) => (
              <li key={caption.segmentId}>
                <p className="flex items-center gap-2 text-xs text-[#9AA0A6]">
                  <span
                    className="inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold text-[#202124]"
                    style={{ background: caption.source === 'sign' ? '#8AB4F8' : '#81C995' }}
                    aria-hidden="true"
                  >
                    {caption.speakerName.charAt(0).toUpperCase()}
                  </span>
                  <span className="font-medium text-[#E8EAED]">{caption.speakerName}</span>
                  <span
                    className="rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                    style={{
                      background: caption.source === 'sign' ? 'rgba(138,180,248,0.18)' : 'rgba(129,201,149,0.18)',
                      color: caption.source === 'sign' ? '#8AB4F8' : '#81C995',
                    }}
                  >
                    {caption.source === 'sign' ? '🤟 Sign' : '🎤 Speech'}
                  </span>
                </p>

                {/* Interim text is grey and turns white when final, so a
                    reader can tell settled words from ones still being
                    revised. */}
                <p
                  className={`${textClass} break-words ${
                    caption.isFinal ? 'text-white' : 'text-[#9AA0A6]'
                  }`}
                >
                  {caption.text}
                </p>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
