import { useId, useState } from 'react';

import Icon from './Icon';

/**
 * An outlined text field with a floating label.
 *
 * The label floats when the field is focused OR non-empty. The second half
 * matters: a browser that autofills email and password never fires focus, so
 * a float driven by focus alone leaves the label sitting on top of the
 * autofilled text.
 *
 * `error` renders beneath the field in red and wires aria-describedby, so the
 * message is announced rather than only seen.
 */
export default function TextField({
  label,
  type = 'text',
  value,
  onChange,
  error,
  hint,
  autoComplete,
  required = false,
  disabled = false,
  icon,
  onKeyDown,
  placeholder,
  name,
  inputRef,
  className = '',
}) {
  const id = useId();
  const [focused, setFocused] = useState(false);
  const [revealed, setRevealed] = useState(false);

  const isPassword = type === 'password';
  const effectiveType = isPassword && revealed ? 'text' : type;
  const floated = focused || String(value ?? '').length > 0 || Boolean(placeholder);

  const borderColor = error
    ? 'border-light-danger'
    : focused
      ? 'border-light-blue'
      : 'border-light-border';

  return (
    <div className={className}>
      <div className={`relative rounded-card border ${borderColor} ${focused && !error ? 'ring-1 ring-light-blue' : ''} transition-colors`}>
        {icon ? (
          <Icon
            name={icon}
            size={20}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-light-muted"
          />
        ) : null}

        <label
          htmlFor={id}
          className={`pointer-events-none absolute bg-light-bg px-1 transition-all duration-150
                      ${icon && !floated ? 'left-10' : 'left-3'}
                      ${floated
                        ? `-top-2 text-xs ${error ? 'text-light-danger' : focused ? 'text-light-blue' : 'text-light-muted'}`
                        : 'top-1/2 -translate-y-1/2 text-base text-light-muted'}`}
        >
          {label}
          {required ? <span aria-hidden="true"> *</span> : null}
        </label>

        <input
          id={id}
          ref={inputRef}
          name={name}
          type={effectiveType}
          value={value ?? ''}
          placeholder={placeholder}
          onChange={(event) => onChange?.(event.target.value)}
          onKeyDown={onKeyDown}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          autoComplete={autoComplete}
          required={required}
          disabled={disabled}
          aria-invalid={error ? true : undefined}
          aria-describedby={error || hint ? `${id}-msg` : undefined}
          className={`h-14 w-full rounded-card bg-transparent text-base text-light-text
                      outline-none placeholder:text-light-muted disabled:opacity-60
                      ${icon ? 'pl-10' : 'pl-3'} ${isPassword ? 'pr-12' : 'pr-3'}`}
        />

        {isPassword ? (
          <button
            type="button"
            onClick={() => setRevealed((shown) => !shown)}
            aria-label={revealed ? 'Hide password' : 'Show password'}
            className="absolute right-2 top-1/2 grid h-10 w-10 -translate-y-1/2 place-items-center
                       rounded-full text-light-muted transition-colors hover:bg-light-surface"
          >
            <Icon name={revealed ? 'visibility_off' : 'visibility'} size={20} />
          </button>
        ) : null}
      </div>

      {error || hint ? (
        <p
          id={`${id}-msg`}
          className={`mt-1.5 px-1 text-xs ${error ? 'text-light-danger' : 'text-light-muted'}`}
        >
          {error || hint}
        </p>
      ) : null}
    </div>
  );
}
