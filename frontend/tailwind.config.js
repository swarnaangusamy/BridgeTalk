/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Accessibility is the point of this project, so the palette is chosen
        // for contrast, not decoration. Every foreground/background pair used
        // in the UI must clear WCAG AA (4.5:1 for body text, 3:1 for large
        // text and UI components).
        ink: {
          900: '#0b1020', // page background (dark surface)
          800: '#121a33', // panel background
          700: '#1c2745', // raised panel / border
        },
        bridge: {
          400: '#7dd3fc', // accent on dark  — 9.2:1 on ink-900
          500: '#38bdf8', // primary action  — 7.4:1 on ink-900
          600: '#0284c7', // primary action on light backgrounds
        },
        signal: {
          ok: '#4ade80',   // high confidence / connected
          warn: '#fbbf24', // low confidence / reconnecting
          bad: '#f87171',  // error / disconnected
        },
      },
      fontSize: {
        // Subtitles must be at least 22px and readable over live video.
        subtitle: ['1.5rem', { lineHeight: '2rem', fontWeight: '600' }],
      },
    },
  },
  plugins: [],
};
