import { useRef } from 'react';

import Icon from './Icon';
import { useDismiss } from './useDismiss';

/**
 * A dropdown menu anchored to whatever triggered it.
 *
 * The caller owns the open state and renders the trigger, because the triggers
 * differ too much to generalise — one is an avatar, one is a three-dot icon
 * button, one is a pill-shaped "New meeting" button.
 */
export function Menu({ open, onClose, align = 'right', children, className = '', labelledBy }) {
  const ref = useRef(null);
  useDismiss(ref, onClose, open);

  if (!open) return null;

  return (
    <div
      ref={ref}
      role="menu"
      aria-labelledby={labelledBy}
      className={`absolute z-50 mt-2 min-w-[240px] overflow-hidden rounded-card
                  bg-light-bg py-2 shadow-menu animate-fade-in
                  ${align === 'right' ? 'right-0' : 'left-0'} ${className}`}
    >
      {children}
    </div>
  );
}

export function MenuItem({ icon, children, onClick, disabled = false, destructive = false, description }) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={onClick}
      className={`flex w-full items-start gap-3 px-4 py-2.5 text-left text-sm
                  transition-colors disabled:cursor-not-allowed disabled:opacity-50
                  ${destructive ? 'text-light-danger hover:bg-light-danger/[.08]' : 'text-light-text hover:bg-light-surface'}`}
    >
      {icon ? <Icon name={icon} size={20} className="mt-px shrink-0 text-light-muted" /> : null}
      <span className="min-w-0">
        <span className="block">{children}</span>
        {description ? (
          <span className="mt-0.5 block text-xs text-light-muted">{description}</span>
        ) : null}
      </span>
    </button>
  );
}

export function MenuDivider() {
  return <hr className="my-2 border-light-border" />;
}

export function MenuHeader({ children }) {
  return <div className="px-4 pb-2 pt-1">{children}</div>;
}
