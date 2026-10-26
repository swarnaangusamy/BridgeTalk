import { Link } from 'react-router-dom';

/**
 * BridgeTalk's own mark and name.
 *
 * Deliberately not Google's logo, name or font — the specification asks for
 * Meet's LAYOUT, in this product's identity.
 *
 * The mark is inline SVG rather than an image file: two hands bridged by a
 * line of text, which is literally what the product does. Inline means it
 * inherits currentColor, so the same component works on the white pages and
 * on the dark lobby without a second asset.
 */
export function LogoMark({ size = 28, className = '' }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <rect width="32" height="32" rx="8" fill="#1A73E8" />
      {/* left pier */}
      <path d="M8 21V13a2 2 0 1 1 4 0v8" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
      {/* right pier */}
      <path d="M20 21v-8a2 2 0 1 1 4 0v8" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
      {/* the span between them — the bridge, and the caption line */}
      <path d="M12 16h8" stroke="#8AB4F8" strokeWidth="2" strokeLinecap="round" />
      <path d="M10 24h12" stroke="#fff" strokeWidth="2" strokeLinecap="round" opacity=".55" />
    </svg>
  );
}

export default function Logo({ to = '/', size = 28, dark = false, className = '' }) {
  const content = (
    <>
      <LogoMark size={size} />
      <span
        className={`text-[22px] font-normal tracking-tight ${dark ? 'text-dark-text' : 'text-light-text'}`}
      >
        BridgeTalk
      </span>
    </>
  );

  if (!to) {
    return <span className={`flex items-center gap-2 ${className}`}>{content}</span>;
  }

  return (
    <Link
      to={to}
      aria-label="BridgeTalk — go to home"
      className={`flex items-center gap-2 rounded ${className}`}
    >
      {content}
    </Link>
  );
}
