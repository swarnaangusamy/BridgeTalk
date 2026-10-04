/**
 * A Material Symbols glyph.
 *
 * The icon's NAME is its text content — Material Symbols are a ligature font,
 * so the string "mic" is rendered as the microphone glyph by the font itself.
 *
 * `aria-hidden` is not optional. Without it a screen reader announces the
 * literal ligature text, so a mute button would read as "mic mic". Every
 * caller is an IconButton or a labelled element that carries the real name.
 */
export default function Icon({ name, size = 24, filled = false, className = '' }) {
  return (
    <span
      aria-hidden="true"
      className={`material-symbols-outlined${filled ? ' filled' : ''} ${className}`}
      style={{ fontSize: `${size}px`, width: `${size}px`, height: `${size}px` }}
    >
      {name}
    </span>
  );
}
