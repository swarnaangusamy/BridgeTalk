import { useEffect } from 'react';

/**
 * Close a popup on Escape, or on a pointer press outside it.
 *
 * Shared by Menu and Dialog so the two cannot develop different ideas about
 * what "dismiss" means.
 *
 * `pointerdown` rather than `click`: a click fires after the mouse is
 * released, so a press that starts outside and finishes inside the popup
 * would not close it. `mousedown` alone would miss touch.
 *
 * The listener is captured on `document` rather than attached to a backdrop
 * element, because a menu has no backdrop — the page behind it stays live.
 */
export function useDismiss(ref, onDismiss, enabled = true) {
  useEffect(() => {
    if (!enabled) return undefined;

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onDismiss();
      }
    };

    const onPointerDown = (event) => {
      if (!ref.current?.contains(event.target)) onDismiss();
    };

    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('pointerdown', onPointerDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('pointerdown', onPointerDown);
    };
  }, [ref, onDismiss, enabled]);
}
