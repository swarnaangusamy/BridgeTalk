import Icon from '../ui/Icon';

/**
 * The 360px panel that slides in from the right of the meeting.
 *
 * IT IS A SIBLING OF THE STAGE, NOT AN OVERLAY
 * --------------------------------------------
 * The specification says the stage resizes when a panel opens. So this sits
 * beside the stage in a flex row and takes 360px out of it, rather than floating
 * on top. Floating would be less code and is what most implementations do, but
 * it would cover the remote participant — and covering the person who is
 * signing, in this product, defeats the point of the call.
 *
 * Below `md` it does become an overlay, because 360px of a 700px-wide window
 * would leave the video unusably narrow. That is the one width where covering
 * the video is the better trade.
 *
 * Only one panel is open at a time. The parent owns which, so opening People
 * closes Transcript without either panel knowing about the other.
 */
export default function SidePanel({ open, title, onClose, children, footer }) {
  if (!open) return null;

  return (
    <aside
      aria-label={title}
      className="on-dark absolute inset-y-0 right-0 z-30 flex w-full flex-col
                 border-l border-dark-surface bg-dark-raised animate-slide-in-right
                 md:static md:z-auto md:w-panel md:shrink-0"
    >
      <header className="flex h-14 shrink-0 items-center justify-between gap-3 px-4">
        <h2 className="min-w-0 truncate text-base font-medium text-dark-text">{title}</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label={`Close ${title}`}
          className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-dark-muted
                     transition-colors hover:bg-dark-surface"
        >
          <Icon name="close" size={20} />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">{children}</div>

      {footer ? (
        <div className="shrink-0 border-t border-dark-surface p-4">{footer}</div>
      ) : null}
    </aside>
  );
}
