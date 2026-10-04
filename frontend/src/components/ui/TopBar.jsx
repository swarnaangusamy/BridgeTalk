import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { useAuth } from '../../context/AuthContext';
import { useClock } from '../../hooks/useClock';
import { formatClockTime, formatShortDate } from '../../utils/formatters';
import Avatar from './Avatar';
import Icon from './Icon';
import Logo from './Logo';
import { Menu, MenuDivider, MenuItem } from './Menu';

/**
 * The 64 px bar at the top of every page except the lobby and the meeting.
 *
 * Left: logo and name, linking home. Right: the time and date, then the user's
 * avatar opening a menu with their name, email, History and Sign out.
 *
 * The clock is hidden below `sm`. On a narrow screen it competes with the logo
 * for the same row, and the time is the less useful of the two — the phone
 * shows it in the status bar anyway.
 */
export default function TopBar({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const now = useClock();
  const [menuOpen, setMenuOpen] = useState(false);
  const triggerRef = useRef(null);

  const handleSignOut = () => {
    setMenuOpen(false);
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <header className="flex h-topbar shrink-0 items-center justify-between gap-4 px-4 sm:px-6">
      <Logo to="/" />

      <div className="flex items-center gap-2 sm:gap-4">
        {children}

        <p className="hidden text-sm text-light-muted sm:block">
          {formatClockTime(now)} · {formatShortDate(now)}
        </p>

        <div className="relative">
          <button
            ref={triggerRef}
            type="button"
            id="account-menu-trigger"
            onClick={() => setMenuOpen((open) => !open)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            aria-label={`Account: ${user?.name ?? 'signed in user'}`}
            className="grid h-10 w-10 place-items-center rounded-full transition-colors hover:bg-light-surface"
          >
            <Avatar name={user?.name ?? ''} size={32} />
          </button>

          <Menu
            open={menuOpen}
            onClose={() => setMenuOpen(false)}
            labelledBy="account-menu-trigger"
            className="min-w-[280px]"
          >
            <div className="flex items-center gap-3 px-4 pb-3 pt-1">
              <Avatar name={user?.name ?? ''} size={40} />
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-light-text">{user?.name}</p>
                <p className="truncate text-xs text-light-muted">{user?.email}</p>
              </div>
            </div>
            <MenuDivider />
            <MenuItem icon="history" onClick={() => { setMenuOpen(false); navigate('/history'); }}>
              History
            </MenuItem>
            <MenuItem icon="videocam" onClick={() => { setMenuOpen(false); navigate('/detect'); }}>
              Sign recognition check
            </MenuItem>
            <MenuDivider />
            <MenuItem icon="logout" onClick={handleSignOut}>
              Sign out
            </MenuItem>
          </Menu>
        </div>
      </div>
    </header>
  );
}

/**
 * A top bar for pages that are a step back from Home — History and the
 * transcript — with a back arrow and a title beside the logo.
 */
export function SubPageTopBar({ backTo, backLabel = 'Back', title }) {
  return (
    <header className="flex h-topbar shrink-0 items-center gap-3 border-b border-light-border px-4 sm:px-6">
      <Link
        to={backTo}
        aria-label={backLabel}
        className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-light-muted
                   transition-colors hover:bg-light-surface"
      >
        <Icon name="arrow_back" size={22} />
      </Link>
      <h1 className="min-w-0 truncate text-lg font-medium text-light-text">{title}</h1>
    </header>
  );
}
