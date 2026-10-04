/**
 * Date, time and duration formatting.
 *
 * All of it in one place because these strings appear on five pages and in the
 * exported transcript, and "9:05 AM" on one page with "09:05" on another is
 * the kind of inconsistency that makes an interface feel unfinished.
 *
 * Locale is left to the browser (`undefined`) rather than pinned to en-IN, so
 * the user's own OS setting decides. The one exception is the control-bar
 * clock, which the specification fixes as `h:mm AM/PM`.
 */

/** `9:05 AM` — the format the specification names for the control bar. */
export function formatClockTime(date) {
  if (!date) return '';
  return new Date(date)
    .toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
    .replace(/\u202f/g, ' '); // some runtimes use a narrow no-break space
}

/** `Sat, 4 Oct` — the top bar's date, kept short so it fits beside the clock. */
export function formatShortDate(date) {
  if (!date) return '';
  return new Date(date).toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  });
}

/** `4 Oct 2026, 9:05 AM` — meeting cards and history rows. */
export function formatDateTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return `${date.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })}, ${formatClockTime(date)}`;
}

/** `9:05:07 AM` — transcript entries, where the second matters. */
export function formatTimeWithSeconds(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date
    .toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    })
    .replace(/\u202f/g, ' ');
}

/**
 * `1h 04m`, `12m 30s`, `45s`.
 *
 * Returns null rather than "0s" when the meeting has no end yet, so callers
 * can show "In progress" instead of a duration that is really unknown.
 */
export function formatDuration(startedAt, endedAt) {
  if (!startedAt || !endedAt) return null;
  const ms = new Date(endedAt).getTime() - new Date(startedAt).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  return formatElapsed(Math.floor(ms / 1000));
}

/** Seconds to `1h 04m` / `12m 30s` / `45s`. */
export function formatElapsed(totalSeconds) {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;

  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, '0')}m`;
  if (minutes > 0) return `${minutes}m ${String(rest).padStart(2, '0')}s`;
  return `${rest}s`;
}

/**
 * Normalise a meeting code for display and for lookup.
 *
 * Uppercase and trim, and NOTHING else. An earlier version re-grouped the
 * characters into the generator's `ABC-DEF` shape, which quietly broke the
 * seeded demo meeting: its code is `DEMO-01`, four characters then two, so
 * regrouping turned it into `DEM-O01` and the join failed with "meeting not
 * found". Codes are opaque strings matched for equality — reformatting one is
 * never safe.
 *
 * Uppercasing is not cosmetic. Codes are stored uppercase and compared with
 * `=`, which is case-insensitive under MySQL's default collation but
 * case-SENSITIVE under SQLite — and SQLite is the documented zero-setup
 * fallback. A lowercase paste would join under one backend and 404 under the
 * other.
 */
export function formatMeetingCode(code) {
  if (!code) return '';
  return String(code).trim().toUpperCase();
}

/**
 * Pull a meeting code out of whatever the user pasted.
 *
 * The Home page's join box accepts a bare code, a hyphenated code, or a full
 * meeting or lobby URL, because all three are things people actually paste.
 * Returns the code as the backend stores it, or null when nothing code-shaped
 * is present — which is what drives the inline "Check your meeting code"
 * error.
 *
 * A hyphen the user typed is KEPT where they typed it, rather than moved to
 * position 3. See formatMeetingCode for what that cost when it was not.
 */
export function parseMeetingCode(input) {
  if (!input) return null;
  const trimmed = String(input).trim();

  // A URL: take the segment after /lobby/ or /meeting/.
  const fromUrl = trimmed.match(/(?:lobby|meeting)\/([a-zA-Z0-9-]+)/);
  const candidate = (fromUrl ? fromUrl[1] : trimmed).toUpperCase();

  // Already hyphenated — trust the grouping as given.
  if (/^[A-Z0-9]{2,8}-[A-Z0-9]{2,8}$/.test(candidate)) return candidate;

  // Six bare characters — the generator's canonical two groups of three.
  if (/^[A-Z0-9]{6}$/.test(candidate)) return `${candidate.slice(0, 3)}-${candidate.slice(3)}`;

  return null;
}
