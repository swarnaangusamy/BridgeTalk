import Icon from './Icon';

/**
 * A round icon button with a tooltip and an accessible label.
 *
 * The specification requires BOTH on every icon button, and they are different
 * things: the tooltip is for a sighted user hovering, the label is what a
 * screen reader reads. They come from one `label` prop so they cannot drift
 * apart, with `shortcut` appended to the tooltip only.
 *
 * The tooltip is CSS-only (group-hover) rather than the native `title`
 * attribute. Native titles take about a second to appear, cannot be styled to
 * read against the dark control bar, and never show on a keyboard focus —
 * which would leave a keyboard user with no tooltip at all.
 */
export default function IconButton({
  icon,
  label,
  shortcut,
  onClick,
  active = false,
  danger = false,
  disabled = false,
  size = 48,
  iconSize = 24,
  variant = 'dark',
  tooltipSide = 'top',
  className = '',
  children,
  ...rest
}) {
  const tip = shortcut ? `${label} (${shortcut})` : label;

  const palette =
    variant === 'dark'
      ? {
          base: 'bg-dark-surface text-dark-text hover:brightness-125',
          active: 'bg-dark-accent text-dark-bg hover:brightness-95',
          danger: 'bg-dark-danger text-white hover:brightness-110',
          off: 'bg-dark-danger text-white hover:brightness-110',
        }
      : {
          base: 'bg-transparent text-light-muted hover:bg-light-text/[.06]',
          active: 'bg-light-blue/[.12] text-light-blue',
          danger: 'bg-transparent text-light-danger hover:bg-light-danger/[.08]',
          off: 'bg-light-danger text-white',
        };

  const tone = danger ? palette.danger : active ? palette.active : palette.base;

  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={label}
        aria-pressed={rest['aria-pressed'] ?? (active ? true : undefined)}
        className={`grid shrink-0 place-items-center rounded-full transition
                    disabled:cursor-not-allowed disabled:opacity-40
                    ${tone} ${className}`}
        style={{ width: size, height: size }}
        {...rest}
      >
        {children ?? <Icon name={icon} size={iconSize} />}
      </button>

      {/* pointer-events-none so the tooltip can never swallow the click it is
          describing — a real bug the first time a tooltip overlaps its own
          button. */}
      <span
        role="tooltip"
        className={`pointer-events-none absolute left-1/2 z-50 -translate-x-1/2
                    whitespace-nowrap rounded bg-[#202124] px-2 py-1 text-xs
                    font-medium text-white opacity-0 shadow-menu transition-opacity
                    group-hover:opacity-100 group-focus-within:opacity-100
                    ${tooltipSide === 'bottom' ? 'top-full mt-2' : 'bottom-full mb-2'}`}
      >
        {tip}
      </span>
    </span>
  );
}
