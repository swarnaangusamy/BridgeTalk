import { useId } from 'react';

/**
 * A compact labelled dropdown, used for device pickers and settings.
 *
 * A native <select> on purpose. A custom listbox would have to reimplement
 * keyboard navigation, type-ahead and the mobile picker, and would still be
 * worse than the one the OS already provides — and these are the controls a
 * user reaches for when their microphone is not working, which is the worst
 * possible moment for a bespoke widget.
 */
export default function Select({
  label,
  value,
  onChange,
  options,
  disabled = false,
  hint,
  icon,
  className = '',
}) {
  const id = useId();

  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-light-muted">
        {label}
      </label>
      <div className="relative">
        {icon ? (
          <span
            aria-hidden="true"
            className="material-symbols-outlined pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-light-muted"
            style={{ fontSize: 18 }}
          >
            {icon}
          </span>
        ) : null}
        <select
          id={id}
          value={value ?? ''}
          disabled={disabled || options.length === 0}
          onChange={(event) => onChange?.(event.target.value)}
          aria-describedby={hint ? `${id}-hint` : undefined}
          className={`h-10 w-full appearance-none rounded-card border border-light-border
                      bg-light-bg pr-9 text-sm text-light-text outline-none
                      transition-colors focus:border-light-blue disabled:opacity-60
                      ${icon ? 'pl-10' : 'pl-3'}`}
        >
          {options.length === 0 ? <option value="">No devices found</option> : null}
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <span
          aria-hidden="true"
          className="material-symbols-outlined pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-light-muted"
          style={{ fontSize: 20 }}
        >
          expand_more
        </span>
      </div>
      {hint ? (
        <p id={`${id}-hint`} className="mt-1 text-xs text-light-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
