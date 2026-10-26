/** @type {import('tailwindcss').Config} */

/**
 * The palette is fixed by the interface specification, which asks for Google
 * Meet's layout and behaviour in BridgeTalk's own branding. Two separate
 * palettes, because the product genuinely has two environments:
 *
 *   `light.*`  every page outside a meeting — login, home, lobby chrome,
 *              history, transcript. White, high contrast, document-like.
 *   `dark.*`   the meeting room only. Dark surfaces keep attention on the
 *              video and the captions, which is the whole point of the page.
 *
 * Contrast is not decoration here; this is an accessibility project, so the
 * pairs actually used are checked against WCAG AA (4.5:1 body, 3:1 large text
 * and UI components):
 *
 *   light.text    #202124 on #FFFFFF  → 16.1:1
 *   light.muted   #5F6368 on #FFFFFF  →  5.9:1
 *   light.blue    #1A73E8 on #FFFFFF  →  4.6:1
 *   dark.text     #E8EAED on #202124  → 14.0:1
 *   dark.muted    #9AA0A6 on #202124  →  6.0:1
 *   dark.accent   #8AB4F8 on #202124  →  8.4:1
 *   dark.danger   #EA4335 on #202124  →  4.3:1  (used for large text and
 *                                               icon buttons only, never for
 *                                               body copy)
 */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Roboto', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Helvetica Neue', 'Arial', 'sans-serif'],
      },
      colors: {
        light: {
          bg: '#FFFFFF',
          surface: '#F8F9FA',
          text: '#202124',
          muted: '#5F6368',
          border: '#DADCE0',
          blue: '#1A73E8',
          bluehover: '#1765CC',
          danger: '#D93025',
        },
        dark: {
          bg: '#202124',
          surface: '#3C4043',
          raised: '#292A2D',
          text: '#E8EAED',
          muted: '#9AA0A6',
          accent: '#8AB4F8',
          danger: '#EA4335',
        },
      },
      borderRadius: {
        // Named after what they are for, so a tile and a card cannot drift
        // apart by someone reaching for a different number.
        card: '8px',
        tile: '12px',
        dialog: '8px',
      },
      height: {
        topbar: '64px',
        controlbar: '80px',
        captions: '140px',
      },
      width: {
        panel: '360px',
      },
      maxWidth: {
        caption: '900px',
        transcript: '800px',
        authcard: '400px',
      },
      fontSize: {
        // The specification sets caption text at 22px, and the three caption
        // sizes offered in Settings scale from it.
        caption: ['22px', { lineHeight: '30px' }],
        'caption-lg': ['28px', { lineHeight: '38px' }],
        'caption-xl': ['34px', { lineHeight: '46px' }],
        display: ['44px', { lineHeight: '52px', fontWeight: '400' }],
      },
      boxShadow: {
        dialog: '0 1px 3px rgba(60,64,67,.3), 0 4px 8px 3px rgba(60,64,67,.15)',
        menu: '0 2px 6px 2px rgba(60,64,67,.15), 0 1px 2px rgba(60,64,67,.3)',
        tile: '0 1px 2px rgba(0,0,0,.3), 0 2px 6px 2px rgba(0,0,0,.15)',
      },
      transitionDuration: { 150: '150ms' },
      keyframes: {
        'slide-in-right': {
          from: { transform: 'translateX(100%)' },
          to: { transform: 'translateX(0)' },
        },
        'toast-in': {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
      },
      animation: {
        'slide-in-right': 'slide-in-right 200ms cubic-bezier(0,0,.2,1)',
        'toast-in': 'toast-in 150ms ease-out',
        'fade-in': 'fade-in 150ms ease-out',
      },
    },
  },
  plugins: [],
};
