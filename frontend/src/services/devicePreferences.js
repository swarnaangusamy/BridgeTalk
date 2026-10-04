/**
 * Device choices for the current meeting, in session storage.
 *
 * WHY NOT THE URL
 * ---------------
 * These used to be query parameters on the join link. A `deviceId` is a stable
 * hardware identifier, so that put a fingerprintable detail about the user's
 * machine into a URL they were actively encouraged to copy into a chat — and
 * into browser history, and into Referer headers.
 *
 * WHY SESSION AND NOT LOCAL STORAGE
 * ---------------------------------
 * "Which microphone for this meeting" should not outlive the tab. A user who
 * plugs in a headset for one call should not find it still selected a week
 * later on a machine where it is no longer attached — which presents as a
 * camera that will not start, with no clue why.
 *
 * Every access is wrapped: storage throws in a private window with site data
 * blocked, and a device preference must never be what stops someone joining.
 */

const KEY = 'bridgetalk.devices';

export function saveDevicePreferences(preferences) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(preferences));
  } catch {
    // Not fatal: the meeting falls back to the system default devices.
  }
}

export function loadDevicePreferences() {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return typeof parsed === 'object' && parsed !== null ? parsed : null;
  } catch {
    return null;
  }
}

export function clearDevicePreferences() {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* nothing to clear */
  }
}
