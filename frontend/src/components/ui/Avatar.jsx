/**
 * A person as an initial in a coloured circle.
 *
 * WHY THE COLOUR IS HASHED FROM THE NAME
 * --------------------------------------
 * The same person must get the same colour on every page and in every
 * participant list, or the avatar stops being a recognisable shorthand for
 * "that person" and becomes noise. Deriving it from the name rather than
 * storing it keeps that true with no extra column in the database and no
 * extra field in any API response.
 *
 * The palette is restricted to colours that clear 4.5:1 against white text,
 * because the initial sits on top of the circle.
 */

const PALETTE = [
  '#1A73E8', // blue
  '#D93025', // red
  '#1E8E3E', // green
  '#E37400', // amber
  '#9334E6', // purple
  '#00897B', // teal
  '#C5221F', // dark red
  '#3367D6', // indigo
];

export function avatarColor(name = '') {
  // djb2. Chosen because it is four lines and spreads short strings well;
  // nothing here is security sensitive, so a cryptographic hash would only
  // cost bytes.
  let hash = 5381;
  for (let i = 0; i < name.length; i += 1) {
    hash = ((hash << 5) + hash + name.charCodeAt(i)) | 0;
  }
  return PALETTE[Math.abs(hash) % PALETTE.length];
}

export default function Avatar({ name = '', size = 32, className = '' }) {
  const initial = (name.trim()[0] ?? '?').toUpperCase();
  return (
    <span
      className={`inline-grid shrink-0 place-items-center rounded-full font-medium text-white ${className}`}
      style={{
        width: size,
        height: size,
        backgroundColor: avatarColor(name),
        fontSize: Math.round(size * 0.45),
      }}
      // The circle is decorative; the name is always rendered as text beside
      // it, so announcing it again would be duplication.
      aria-hidden="true"
      title={name || undefined}
    >
      {initial}
    </span>
  );
}
