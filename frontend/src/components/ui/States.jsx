import { Link } from 'react-router-dom';

import Icon from './Icon';

/**
 * Loading, empty and error states.
 *
 * The specification asks for all three on every page. They live together in
 * one file because their job is to look identical everywhere — a page that
 * invents its own "nothing here yet" is how an interface starts feeling like
 * several different products.
 */

export function Spinner({ size = 24, className = '' }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={`inline-block animate-spin rounded-full border-2 border-light-border
                  border-t-light-blue ${className}`}
      style={{ width: size, height: size }}
    />
  );
}

export function LoadingState({ message = 'Loading…', className = '' }) {
  return (
    <div className={`grid place-items-center gap-3 py-16 ${className}`}>
      <Spinner size={28} />
      <p className="text-sm text-light-muted" role="status">
        {message}
      </p>
    </div>
  );
}

/** Grey blocks shaped like the rows they stand in for. */
export function SkeletonRow({ className = '' }) {
  return (
    <div className={`flex animate-pulse items-center gap-4 rounded-card border border-light-border p-4 ${className}`}>
      <div className="h-10 w-10 shrink-0 rounded-full bg-light-surface" />
      <div className="min-w-0 flex-1 space-y-2">
        <div className="h-4 w-1/3 rounded bg-light-surface" />
        <div className="h-3 w-1/2 rounded bg-light-surface" />
      </div>
      <div className="h-9 w-32 shrink-0 rounded-full bg-light-surface" />
    </div>
  );
}

export function EmptyState({ icon = 'inbox', title, body, actionLabel, actionTo, onAction }) {
  return (
    <div className="grid place-items-center gap-3 rounded-card border border-dashed border-light-border px-6 py-14 text-center">
      <span
        aria-hidden="true"
        className="grid h-16 w-16 place-items-center rounded-full bg-light-surface text-light-muted"
      >
        <Icon name={icon} size={32} />
      </span>
      <h3 className="text-base font-medium text-light-text">{title}</h3>
      {body ? <p className="max-w-sm text-sm text-light-muted">{body}</p> : null}
      {actionTo ? (
        <Link to={actionTo} className="btn-outlined mt-2">
          {actionLabel}
        </Link>
      ) : actionLabel ? (
        <button type="button" onClick={onAction} className="btn-outlined mt-2">
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

export function ErrorState({ title = 'Something went wrong', body, onRetry, retryLabel = 'Try again' }) {
  return (
    <div
      role="alert"
      className="grid place-items-center gap-3 rounded-card border border-light-danger/30
                 bg-light-danger/[.04] px-6 py-12 text-center"
    >
      <span aria-hidden="true" className="text-light-danger">
        <Icon name="error" size={32} />
      </span>
      <h3 className="text-base font-medium text-light-text">{title}</h3>
      {body ? <p className="max-w-md text-sm text-light-muted">{body}</p> : null}
      {onRetry ? (
        <button type="button" onClick={onRetry} className="btn-outlined mt-2">
          {retryLabel}
        </button>
      ) : null}
    </div>
  );
}

/** An inline red message under a form, for a failed submit. */
export function FormError({ children }) {
  if (!children) return null;
  return (
    <p role="alert" className="flex items-start gap-2 text-sm text-light-danger">
      <Icon name="error" size={18} className="mt-px shrink-0" />
      <span>{children}</span>
    </p>
  );
}
