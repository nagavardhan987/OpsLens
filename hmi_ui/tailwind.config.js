/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        se: {
          green: '#00A344',
          darkgreen: '#007A33',
          lightgreen: '#00D65A',
          lime: '#9AD627',
          charcoal: '#1A1D20',
        },
        hmi: {
          bg: '#0B0F17',
          surface: '#121A26',
          card: '#182333',
          cardHover: '#1E2C40',
          border: '#24344D',
          borderHighlight: '#3B82F6',
          textMuted: '#8B9BB4',
          textBright: '#F1F5F9',
          alarmRed: '#EF4444',
          alarmRedGlow: 'rgba(239, 68, 68, 0.25)',
          warningAmber: '#F59E0B',
          healthyGreen: '#10B981',
          accentCyan: '#06B6D4'
        }
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Menlo', 'Consolas', 'Courier New', 'monospace'],
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif']
      }
    },
  },
  plugins: [],
}
