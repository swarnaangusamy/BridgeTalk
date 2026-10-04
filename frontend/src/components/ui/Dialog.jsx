import { useEffect, useRef } from 'react';

import Icon from './Icon';
import { useDismiss } from './useDismiss';

/**
 * A modal dialog: 8px radius and a soft shadow, per the specification.
 *
 * TWO THINGS HERE ARE ACCESSIBILITY, NOT POLISH
 * ---------------------------------------------
 * 1. Focus moves into the dialog when it opens and returns to whatever was
 *    focused before when it closes. Without the return, dismissing a dialog
 *    with Escape drops keyboard focus back to <body> and the user has to tab
 *    from the top of the page again.
 *
 * 2. Tab is trapped inside the panel. A modal that lets Tab wander into the
 *    page behind it is worse than no modal: the focus ring disappears behind
 *    the backdrop and the user cannot see where they are.
 *
 * `closeOnDismiss={false}` is for dialogs that must be answered rather than
 * escaped — the interview-mode acknowledgement uses it.
 */
export default function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  width = 'max-w-md',
  closeOnDismiss = true,
  showClose = true,
}) {
  const panelRef = useRef(null);
  const restoreRef = useRef(null);

  useDismiss(panelRef, onClose, open && closeOnDismiss);

  useEffect(() => {
    if (!open) return undefined;

    restoreRef.current = document.activeElement;

    // Prefer the first genuinely interactive thing; fall back to the panel so
    // a dialog that is pure text still receives Escape.
    const focusable = panelRef.current?.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    (focusable?.[0] ?? panelRef.current)?.focus();

    const onKeyDown = (event) => {
      if (event.key !== 'Tab') return;
      const items = panelRef.current?.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (!items?.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown);
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = overflow;
      restoreRef.current?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100] grid place-items-center bg-black/50 p-4 animate-fade-in">
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : undefined}
        tabIndex={-1}
        className={`w-full ${width} overflow-hidden rounded-dialog bg-light-bg shadow-dialog`}
      >
        {title ? (
          <div className="flex items-start justify-between gap-4 px-6 pt-6">
            <div>
              <h2 className="text-lg font-medium text-light-text">{title}</h2>
              {description ? (
                <p className="mt-1 text-sm text-light-muted">{description}</p>
              ) : null}
            </div>
            {showClose ? (
              <button
                type="button"
                onClick={onClose}
                aria-label="Close dialog"
                className="-mr-2 -mt-2 grid h-10 w-10 shrink-0 place-items-center rounded-full
                           text-light-muted transition-colors hover:bg-light-surface"
              >
                <Icon name="close" size={20} />
              </button>
            ) : null}
          </div>
        ) : null}

        <div className="px-6 py-4">{children}</div>

        {footer ? (
          <div className="flex items-center justify-end gap-2 px-6 pb-6">{footer}</div>
        ) : null}
      </div>
    </div>
  );
}
