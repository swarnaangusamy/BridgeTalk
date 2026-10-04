/**
 * The large caption bar across the bottom of the meeting room.
 *
 * This is the single most important element on the screen for the person
 * relying on it, so the constraints are not cosmetic:
 *   - at least 22px (`text-subtitle` is 24px) — the spec's floor;
 *   - white on a near-opaque dark bar, never text directly over video, because
 *     contrast against a moving background cannot be guaranteed;
 *   - aria-live="polite" so a screen reader announces new captions without
 *     interrupting whatever it is already reading;
 *   - the speaker is always named, since two directions of translation land
 *     in the same bar and "who said that?" must never be ambiguous.
 */
export default function SubtitleBar({ subtitle, textClassName = 'text-subtitle' }) {
  if (!subtitle?.text) {
    return (
      <div className="rounded-xl border border-ink-700 bg-ink-900/95 px-6 py-4">
        <p className="text-center text-slate-500">
          Captions will appear here as either participant signs or speaks.
        </p>
      </div>
    );
  }

  const isSign = subtitle.source === 'sign';
  // An icon as well as a colour and a word: the source must survive colour
  // blindness, a monochrome projector, and a glance from across the room.
  const sourceIcon = isSign ? '🤟' : '🎤';
  const sourceLabel = isSign ? 'Sign' : 'Speech';

  return (
    <div
      className="rounded-xl border border-ink-700 bg-ink-900/95 px-6 py-4"
      aria-live="polite"
      aria-atomic="true"
    >
      <p className="mb-1 flex items-center gap-2 text-sm font-medium text-slate-400">
        <span
          className={`rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${
            isSign ? 'bg-bridge-500/20 text-bridge-400' : 'bg-signal-ok/20 text-signal-ok'
          }`}
        >
          <span aria-hidden="true">{sourceIcon}</span> {sourceLabel}
        </span>
        {subtitle.speaker}
        {/* Interim speech results are revised word by word as more is heard;
            marking them keeps the reader from trusting a half-sentence. */}
        {subtitle.isFinal === false && <span className="italic text-slate-500">· hearing…</span>}
      </p>

      {/* Interim text is lighter and italic, so a reader can tell at a glance
          which words are settled and which may still be revised. */}
      <p
        // Size comes from the caption-size control, not a constant. 22px is the
        // floor, not the ceiling — a caption someone cannot read is not a
        // caption, and this audience is exactly who needs the larger steps.
        className={`${textClassName} break-words ${
          subtitle.isFinal === false ? 'italic text-slate-300/80' : 'text-slate-50'
        }`}
      >
        {subtitle.text}
      </p>
    </div>
  );
}
