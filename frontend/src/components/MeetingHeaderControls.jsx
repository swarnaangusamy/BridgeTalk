import { useCallback, useEffect, useState } from 'react';

/**
 * Meeting timer and copy-link, for the header.
 *
 * The timer counts from the meeting's `started_at` rather than from when this
 * component mounted. That difference matters: a participant who joins ten
 * minutes late, or reloads, should see the meeting's real elapsed time, not
 * their own session length.
 */
export function MeetingTimer({ startedAt }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!startedAt) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [startedAt]);

  if (!startedAt) return null;

  const seconds = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;

  const text =
    hours > 0
      ? `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
      : `${minutes}:${String(secs).padStart(2, '0')}`;

  return (
    <span className="tabular-nums" aria-label={`Meeting running for ${text}`}>
      {text}
    </span>
  );
}

/**
 * Copies the join link, with a visible confirmation.
 *
 * Copies the full URL rather than the bare code, because that is what someone
 * can paste into a chat and have the other person simply click. The code alone
 * requires explaining where to type it.
 *
 * navigator.clipboard needs a secure context, so there is a fallback: on
 * failure the link is shown for manual copying rather than the button silently
 * doing nothing.
 */
export function CopyLinkButton({ code }) {
  const [state, setState] = useState('idle'); // idle | copied | failed
  const link = `${window.location.origin}/lobby/${encodeURIComponent(code)}`;

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(link);
      setState('copied');
      setTimeout(() => setState('idle'), 2000);
    } catch {
      // Clipboard access needs HTTPS or localhost. Rather than fail silently,
      // show the link so it can be copied by hand.
      setState('failed');
    }
  }, [link]);

  return (
    <span className="inline-flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={copy}
        className="rounded-md border border-ink-700 px-2 py-1 text-xs hover:bg-ink-700"
      >
        {state === 'copied' ? 'Link copied ✓' : 'Copy join link'}
      </button>

      {state === 'failed' && (
        <input
          readOnly
          value={link}
          onFocus={(event) => event.target.select()}
          aria-label="Join link, copy manually"
          className="w-64 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-xs text-slate-200"
        />
      )}
    </span>
  );
}

/**
 * Caption size control.
 *
 * An accessibility feature rather than a preference. The spec's floor is 22px;
 * this raises it further for anyone who needs it, and the choice is remembered
 * so it does not have to be set again every meeting.
 *
 * localStorage is wrapped in try/catch because it throws in a private window
 * with site data blocked, and a caption control must not be the thing that
 * breaks the meeting room.
 */
const SIZES = [
  { id: 'normal', label: 'A', title: 'Normal captions', className: 'text-subtitle' },
  { id: 'large', label: 'A+', title: 'Large captions', className: 'text-[2rem] leading-tight' },
  { id: 'xlarge', label: 'A++', title: 'Extra large captions', className: 'text-[2.6rem] leading-tight' },
];

const STORAGE_KEY = 'bridgetalk.captionSize';

export function useCaptionSize() {
  const [size, setSize] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) ?? 'normal';
    } catch {
      return 'normal';
    }
  });

  const choose = useCallback((next) => {
    setSize(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Private window with site data blocked. The choice still applies for
      // this session; it simply will not be remembered.
    }
  }, []);

  const className = SIZES.find((entry) => entry.id === size)?.className ?? SIZES[0].className;
  return { size, choose, className };
}

export function CaptionSizeControl({ size, onChoose }) {
  return (
    <div
      className="inline-flex items-center gap-1"
      role="group"
      aria-label="Caption text size"
    >
      {SIZES.map((entry) => (
        <button
          key={entry.id}
          type="button"
          onClick={() => onChoose(entry.id)}
          aria-pressed={size === entry.id}
          title={entry.title}
          className={`rounded-md border px-2 py-1 text-xs font-semibold ${
            size === entry.id
              ? 'border-bridge-500 bg-bridge-500/20 text-slate-100'
              : 'border-ink-700 text-slate-300 hover:bg-ink-700'
          }`}
        >
          {entry.label}
        </button>
      ))}
    </div>
  );
}
