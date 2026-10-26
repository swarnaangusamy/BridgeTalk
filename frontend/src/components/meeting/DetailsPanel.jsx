import { useEffect, useRef, useState } from 'react';

import { formatDateTime } from '../../utils/formatters';
import Icon from '../ui/Icon';

/**
 * Meeting details: the title, the code, and the joining link with a copy
 * button.
 *
 * The link is the whole point of this panel. Everything else is context for the
 * person who has been asked "what's the code?" mid-call and needs to read it
 * out without leaving the meeting.
 */
export default function DetailsPanel({ meeting, code }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef(null);

  // Clearing on unmount matters: the panel is unmounted the moment it closes,
  // and a pending timer would call setState on a dead component.
  useEffect(() => () => clearTimeout(timerRef.current), []);

  const link = `${window.location.origin}/lobby/${code}`;

  function copy() {
    navigator.clipboard
      ?.writeText(link)
      .then(() => {
        setCopied(true);
        clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => {
        // clipboard.writeText is unavailable over plain HTTP on a non-localhost
        // origin. The link is selectable text, so copying by hand still works.
      });
  }

  return (
    <div className="flex flex-col gap-5 pt-1">
      <section>
        <h3 className="text-xs font-medium uppercase tracking-wide text-dark-muted">Meeting</h3>
        <p className="mt-1 text-sm text-dark-text">{meeting?.title ?? 'BridgeTalk meeting'}</p>
        {meeting?.created_at ? (
          <p className="mt-0.5 text-xs text-dark-muted">{formatDateTime(meeting.created_at)}</p>
        ) : null}
      </section>

      <section>
        <h3 className="text-xs font-medium uppercase tracking-wide text-dark-muted">
          Meeting code
        </h3>
        <p className="mt-1 select-all font-mono text-lg text-dark-text">{code}</p>
      </section>

      <section>
        <h3 className="text-xs font-medium uppercase tracking-wide text-dark-muted">
          Joining link
        </h3>
        <div className="mt-2 flex items-start gap-2 rounded-card bg-dark-surface p-3">
          <span className="min-w-0 flex-1 select-all break-all text-xs text-dark-text">
            {link}
          </span>
          <button
            type="button"
            onClick={copy}
            aria-label="Copy joining link"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-dark-accent
                       transition-colors hover:bg-white/10"
          >
            <Icon name={copied ? 'check' : 'content_copy'} size={18} />
          </button>
        </div>
        <p aria-live="polite" className="mt-1 h-4 text-xs text-dark-muted">
          {copied ? 'Link copied' : ''}
        </p>
      </section>

      {meeting?.host?.name ? (
        <section>
          <h3 className="text-xs font-medium uppercase tracking-wide text-dark-muted">Host</h3>
          <p className="mt-1 text-sm text-dark-text">{meeting.host.name}</p>
        </section>
      ) : null}

      <p className="rounded-card bg-dark-surface p-3 text-xs leading-relaxed text-dark-muted">
        Your camera never leaves this device. Sign recognition runs in your
        browser and sends only hand coordinates — a few hundred bytes a frame —
        to produce captions.
      </p>
    </div>
  );
}
