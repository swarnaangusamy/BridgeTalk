import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';

/**
 * Short-lived notices at the bottom-left of the meeting: someone joined, left,
 * or started presenting.
 *
 * WHY THE TOASTS ARE DEDUPLICATED
 * -------------------------------
 * WebRTC and the signalling socket both observe a participant arriving, and a
 * reconnect replays the room state. Without a guard the user gets "Swarna
 * joined" three times in two seconds. A toast with the same text as one
 * already on screen refreshes that toast's timer instead of stacking a copy.
 *
 * `aria-live="polite"` rather than "assertive": a join notice must not
 * interrupt a screen reader mid-caption, which is exactly what assertive
 * would do on the one page where captions are the point.
 */

const ToastContext = createContext(null);
const DEFAULT_MS = 4000;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timersRef = useRef(new Map());
  const nextIdRef = useRef(1);

  const dismiss = useCallback((id) => {
    clearTimeout(timersRef.current.get(id));
    timersRef.current.delete(id);
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const show = useCallback(
    (text, { icon = null, durationMs = DEFAULT_MS } = {}) => {
      if (!text) return;

      let id;
      setToasts((current) => {
        const existing = current.find((toast) => toast.text === text);
        if (existing) {
          id = existing.id;
          return current;
        }
        id = nextIdRef.current;
        nextIdRef.current += 1;
        return [...current, { id, text, icon }];
      });

      // Scheduled after the state update so a refreshed toast gets a fresh
      // timer rather than inheriting the old one's remaining time.
      clearTimeout(timersRef.current.get(id));
      timersRef.current.set(
        id,
        setTimeout(() => dismiss(id), durationMs),
      );
    },
    [dismiss],
  );

  const value = useMemo(() => ({ show, dismiss }), [show, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed bottom-24 left-4 z-[90] flex flex-col gap-2"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className="pointer-events-auto flex max-w-sm items-center gap-3 rounded-card
                       bg-[#3C4043] px-4 py-3 text-sm text-dark-text shadow-menu
                       animate-toast-in"
          >
            {toast.icon ? (
              <span className="material-symbols-outlined shrink-0 text-dark-muted" aria-hidden="true" style={{ fontSize: 20 }}>
                {toast.icon}
              </span>
            ) : null}
            <span className="min-w-0">{toast.text}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/**
 * Returns `{ show, dismiss }`.
 *
 * Deliberately returns a no-op `show` outside a provider rather than throwing.
 * Toasts are a courtesy, and a component rendered in a test or in isolation
 * must not crash because nobody wrapped it in a ToastProvider.
 */
export function useToast() {
  return useContext(ToastContext) ?? { show: () => {}, dismiss: () => {} };
}
