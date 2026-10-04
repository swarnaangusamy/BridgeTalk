import { useCallback, useEffect, useState } from 'react';

/**
 * Enumerate cameras and microphones, and let the user pick.
 *
 * THE PERMISSION ORDER MATTERS
 * ----------------------------
 * `enumerateDevices()` returns entries with EMPTY labels until the page has
 * been granted media permission at least once. That is a deliberate
 * anti-fingerprinting measure: a site that has never been allowed the camera
 * should not learn what hardware you own.
 *
 * So the lobby asks for a stream FIRST, then enumerates. Doing it the other way
 * round produces a device list reading "", "", "" — which looks like a bug and
 * is really the browser protecting the user.
 *
 * `devicechange` is watched too, so plugging in a headset mid-lobby updates the
 * list rather than requiring a reload.
 */
export function useMediaDevices({ enabled = true } = {}) {
  const [cameras, setCameras] = useState([]);
  const [microphones, setMicrophones] = useState([]);
  const [permission, setPermission] = useState('unknown'); // unknown|granted|denied
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) {
      setError('This browser cannot list media devices.');
      return;
    }

    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const video = devices.filter((d) => d.kind === 'videoinput');
      const audio = devices.filter((d) => d.kind === 'audioinput');

      setCameras(video);
      setMicrophones(audio);

      // Empty labels are the tell that permission has not been granted yet.
      const labelled = [...video, ...audio].some((d) => d.label);
      setPermission(labelled ? 'granted' : 'unknown');
    } catch (cause) {
      setError(cause.message ?? 'Could not list devices');
    }
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;

    refresh();
    navigator.mediaDevices?.addEventListener?.('devicechange', refresh);
    return () => {
      navigator.mediaDevices?.removeEventListener?.('devicechange', refresh);
    };
  }, [enabled, refresh]);

  return { cameras, microphones, permission, error, refresh, setPermission };
}
