/**
 * ESLint configuration.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * `package.json` has carried a `lint` script and four pinned ESLint packages
 * since Phase 0, but no configuration file, so `npm run lint` exited with
 * "couldn't find a configuration file" and nothing was ever linted.
 *
 * The cost of that was concrete. MeetingRoom.jsx accumulated ELEVEN
 * use-before-define errors: `applyAndRecord`, `addScreenTrack`,
 * `removeScreenSender`, `sendSignal`, `remotePresenter`, `remoteScreenStream`,
 * `interview` and `toggleCamera` were all read during render above the line
 * that initialised them. `const` is hoisted but sits in the temporal dead
 * zone until its initialiser runs, so every one of those threw
 * "Cannot access 'X' before initialization" and took the meeting screen down
 * to the error boundary. A hook's dependency array is the trap: the callback
 * body is deferred and looks fine, but `[screenShare, remotePresenter]` is
 * evaluated immediately.
 *
 * Vite's build does not catch this — it only transforms modules, it does not
 * do scope analysis — so the bundle built cleanly while the page was broken.
 */
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  parserOptions: {
    ecmaVersion: 2022,
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  settings: { react: { version: '18.3' } },
  extends: [
    'eslint:recommended',
    'plugin:react/recommended',
    'plugin:react/jsx-runtime',
    'plugin:react-hooks/recommended',
  ],
  plugins: ['react-refresh'],
  rules: {
    // The rule this project needed. `functions: false` keeps hoisted
    // `function` declarations legal, which the codebase uses deliberately for
    // toggleMic and leaveMeeting; `variables: true` is what catches the TDZ.
    'no-use-before-define': ['error', { functions: false, classes: true, variables: true }],

    // Downgraded to a warning rather than silenced: an unused binding is often
    // a half-wired feature worth seeing, but it must not fail the build.
    'no-unused-vars': ['warn', { args: 'none', ignoreRestSiblings: true }],

    // Advisory. The codebase intentionally omits some dependencies where
    // including them would re-subscribe a WebSocket on every render, and each
    // such omission is commented at the call site.
    'react-hooks/exhaustive-deps': 'warn',

    'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],

    // The MediaPipe and WebRTC code legitimately has empty catch blocks where
    // the failure is genuinely ignorable; those are commented individually.
    'no-empty': ['error', { allowEmptyCatch: true }],

    'react/prop-types': 'off',
  },
};
