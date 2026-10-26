import { useEffect, useRef, useState } from 'react';

import { formatTimeWithSeconds } from '../../utils/formatters';
import Avatar from '../ui/Avatar';
import Icon from '../ui/Icon';
import { Spinner } from '../ui/States';

/**
 * The running transcript, inside the meeting.
 *
 * WHY IT SHOWS PERSISTED ROWS AND NOT THE LIVE CAPTION LIST
 * --------------------------------------------------------
 * The caption rail shows what is being said right now, including interim text
 * that may still change, and it is capped at 40 entries. This panel is the
 * record: everything, in order, as the server actually saved it.
 *
 * Reading from the database rather than the caption store is what makes the two
 * agree with the exported file. If this rendered the in-memory list it would
 * show interim guesses as though they were saved, and it would be missing
 * everything said before this participant joined.
 *
 * It is refreshed by the parent — which knows when a final caption arrived —
 * rather than polling on a timer, so a quiet meeting makes no requests.
 */
export default function LiveTranscriptPanel({ lines, loading, error, onRefresh, onDownload }) {
  const scrollRef = useRef(null);
  const [downloading, setDownloading] = useState(false);

  // Stick to the bottom as new lines arrive, unless the user has scrolled up to
  // read something — yanking them back to the end mid-sentence is worse than
  // missing the newest line.
  const pinnedRef = useRef(true);
  useEffect(() => {
    const element = scrollRef.current;
    if (element && pinnedRef.current) element.scrollTop = element.scrollHeight;
  }, [lines]);

  function handleScroll() {
    const element = scrollRef.current;
    if (!element) return;
    const distanceFromBottom =
      element.scrollHeight - element.scrollTop - element.clientHeight;
    pinnedRef.current = distanceFromBottom < 40;
  }

  async function download(format) {
    setDownloading(true);
    try {
      await onDownload(format);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        {loading && lines.length === 0 ? (
          <div className="grid place-items-center py-10">
            <Spinner size={22} className="border-white/20 border-t-dark-accent" />
          </div>
        ) : error ? (
          <div className="py-8 text-center">
            <p className="text-sm text-dark-danger">{error}</p>
            <button type="button" onClick={onRefresh} className="mt-3 text-sm text-dark-accent hover:underline">
              Try again
            </button>
          </div>
        ) : lines.length === 0 ? (
          <p className="py-8 text-center text-sm text-dark-muted">
            Nothing has been saved yet. Captions are added here as they are
            finalised.
          </p>
        ) : (
          <ol className="flex flex-col gap-3 py-1">
            {lines.map((line) => (
              <li key={line.id} className="flex gap-2.5">
                <Avatar name={line.speaker} size={26} className="mt-0.5" />
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-xs font-medium text-dark-text">{line.speaker}</span>
                    <span className="text-[11px] text-dark-muted">
                      {formatTimeWithSeconds(line.timestamp)}
                    </span>
                    <span className="inline-flex items-center gap-0.5 text-[10px] uppercase tracking-wide text-dark-muted">
                      <Icon name={line.source === 'sign' ? 'sign_language' : 'mic'} size={11} />
                      {line.source === 'sign' ? 'Sign' : 'Speech'}
                    </span>
                  </p>
                  <p className="mt-0.5 break-words text-sm text-dark-text">{line.text}</p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>

      <div className="mt-3 flex shrink-0 items-center justify-between gap-2 border-t border-dark-surface pt-3">
        <span className="text-xs text-dark-muted">
          {lines.length} {lines.length === 1 ? 'entry' : 'entries'}
        </span>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => download('txt')}
            disabled={downloading || lines.length === 0}
            className="flex h-9 items-center gap-1.5 rounded-full px-3 text-xs font-medium
                       text-dark-accent transition-colors hover:bg-white/10
                       disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Icon name="download" size={16} />
            TXT
          </button>
          <button
            type="button"
            onClick={() => download('pdf')}
            disabled={downloading || lines.length === 0}
            className="flex h-9 items-center gap-1.5 rounded-full px-3 text-xs font-medium
                       text-dark-accent transition-colors hover:bg-white/10
                       disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Icon name="picture_as_pdf" size={16} />
            PDF
          </button>
        </div>
      </div>
    </div>
  );
}
