import { useEffect, useRef } from 'react';

import TranscriptDownloadButton from './TranscriptDownloadButton';

/**
 * The running record of the conversation, both directions interleaved.
 *
 * Every line carries a speaker, a timestamp and a source tag. The tag is what
 * makes the transcript honest: a reader can see which lines came out of the
 * sign model — and with what confidence — rather than assuming every line is
 * equally reliable. A transcript that hides its own uncertainty is worse than
 * no transcript.
 */
export default function TranscriptPanel({ lines, meetingId, collapsed, onToggle }) {
  const listRef = useRef(null);
  const pinnedToBottomRef = useRef(true);

  // Auto-scroll to the newest line, but only when the reader is already at the
  // bottom. Yanking the view down while someone is scrolled up reading earlier
  // context is a genuinely hostile behaviour.
  useEffect(() => {
    const element = listRef.current;
    if (element && pinnedToBottomRef.current) {
      element.scrollTop = element.scrollHeight;
    }
  }, [lines]);

  function handleScroll(event) {
    const { scrollTop, scrollHeight, clientHeight } = event.currentTarget;
    pinnedToBottomRef.current = scrollHeight - scrollTop - clientHeight < 40;
  }


  if (collapsed) {
    return (
      <button
        type="button"
        onClick={onToggle}
        className="rounded-lg border border-ink-700 px-3 py-2 text-sm hover:bg-ink-700"
        aria-expanded="false"
      >
        Show transcript ({lines.length})
      </button>
    );
  }

  return (
    <section className="panel flex h-full flex-col" aria-labelledby="transcript-heading">
      <header className="mb-3 flex items-center justify-between gap-2">
        <h2 id="transcript-heading" className="text-lg font-semibold">
          Transcript
        </h2>
        <div className="flex items-center gap-2">
          <TranscriptDownloadButton meetingId={meetingId} />
          <button
            type="button"
            onClick={onToggle}
            className="rounded-md border border-ink-700 px-2 py-1 text-xs hover:bg-ink-700"
            aria-expanded="true"
          >
            Hide
          </button>
        </div>
      </header>

      <ol
        ref={listRef}
        onScroll={handleScroll}
        className="flex-1 space-y-3 overflow-y-auto pr-1"
      >
        {lines.length === 0 && (
          <li className="text-sm text-slate-500">
            Nothing yet. Signed and spoken text will both appear here.
          </li>
        )}

        {lines.map((line) => (
          <li key={line.id} className="border-l-2 border-ink-700 pl-3">
            <p className="flex items-center gap-2 text-xs text-slate-400">
              <span
                className={`rounded px-1.5 py-0.5 font-semibold uppercase ${
                  line.source === 'sign'
                    ? 'bg-bridge-500/20 text-bridge-400'
                    : 'bg-signal-ok/20 text-signal-ok'
                }`}
              >
                {line.source}
              </span>
              <span className="font-medium text-slate-300">{line.speaker}</span>
              <time dateTime={line.timestamp}>
                {new Date(line.timestamp).toLocaleTimeString()}
              </time>
              {line.confidence != null && (
                <span className="tabular-nums">{(line.confidence * 100).toFixed(0)}%</span>
              )}
            </p>
            <p className="mt-0.5 break-words text-slate-100">{line.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
