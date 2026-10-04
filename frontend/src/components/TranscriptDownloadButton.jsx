import { useCallback, useState } from 'react';

import { transcripts as transcriptsApi } from '../services/api';

/**
 * Saves a meeting's transcript as a .txt file.
 *
 * WHY THIS IS A BUTTON AND NOT A LINK
 * -----------------------------------
 * The export endpoint is member-only and authenticated by a bearer token. A
 * plain `<a href>` triggers a browser navigation, and a navigation cannot set
 * request headers — so the server sees no token and answers 401. That was a
 * real bug here: the control looked correct and produced an authentication
 * error instead of a file, silently, unless you had the network tab open.
 *
 * `transcripts.download()` fetches with the header, turns the response into a
 * Blob and saves it. This component owns only the "what is happening right
 * now" state, so each row in a list can be downloading independently.
 */
export default function TranscriptDownloadButton({
  meetingId,
  format = 'txt',
  label = `Download .${format}`,
  className = 'rounded-md border border-ink-700 px-2 py-1 text-xs hover:bg-ink-700 disabled:opacity-50',
}) {
  // 'idle' | 'working' | 'done' | 'error'
  const [state, setState] = useState('idle');
  const [error, setError] = useState(null);

  const handleClick = useCallback(async () => {
    if (!meetingId) return;

    setState('working');
    setError(null);
    try {
      await transcriptsApi.download(meetingId, format);
      setState('done');
      // Return to the neutral label shortly. A button stuck on "Saved" reads
      // as though clicking it again would do nothing.
      setTimeout(() => setState('idle'), 2500);
    } catch (cause) {
      setState('error');
      setError(cause.message ?? 'Download failed');
    }
  }, [meetingId, format]);

  if (!meetingId) return null;

  return (
    <span className="inline-flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={handleClick}
        disabled={state === 'working'}
        className={className}
      >
        {state === 'working' ? 'Saving…' : state === 'done' ? 'Saved ✓' : label}
      </button>

      {error && (
        <span className="text-xs text-signal-bad" role="alert">
          {error}
        </span>
      )}
    </span>
  );
}
