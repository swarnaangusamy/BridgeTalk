import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/**
 * Test configuration.
 *
 * WHY THESE TESTS EXIST
 * ---------------------
 * The interface shipped with eleven use-before-define errors that threw at
 * render time and took the meeting screen down to the error boundary. `vite
 * build` could not catch them — it transforms modules and does no scope
 * analysis — so the bundle built cleanly while the page was broken.
 *
 * ESLint now catches that specific class. These tests catch the broader one: a
 * page that throws when it is actually rendered, for any reason. They mount
 * every route against jsdom with the browser APIs this app needs stubbed, and
 * fail if anything throws.
 *
 * They are deliberately NOT thorough behavioural tests. The behaviour that
 * matters here — a caption appearing on the other person's screen — needs two
 * browsers, a camera and a voice, and is verified by hand. These answer a
 * narrower question that no human should have to re-check after every edit:
 * does each page render at all?
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    include: ['src/**/*.test.{js,jsx}'],
    css: false,
  },
});
