/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Mirror the legacy SPA accent so the React port reads as
        // continuous with the vanilla UI during the transition.
        nexus: {
          accent: '#2563eb',
          surface: '#ffffff',
          muted: '#64748b',
          border: '#e2e8f0',
          // Graph/state semantic colors. Also exported as hex from
          // lib/topology.js (Phase 3) for the Canvas graph, which cannot
          // read Tailwind classes.
          warning: '#f59e0b',
          danger: '#ef4444',
          success: '#10b981',
        },
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['SF Mono', 'Menlo', 'Monaco', 'monospace'],
      },
      backdropBlur: {
        xs: '2px',
        '3xl': '40px',
      },
      boxShadow: {
        'glass-sm': '0 1px 2px rgba(15,23,42,0.04), 0 1px 3px rgba(15,23,42,0.06)',
        glass: '0 4px 16px rgba(15,23,42,0.06), 0 2px 4px rgba(15,23,42,0.04)',
        'glass-lg': '0 12px 32px rgba(15,23,42,0.10), 0 4px 8px rgba(15,23,42,0.05)',
        'glass-glow': '0 0 0 1px rgba(37,99,235,0.10), 0 8px 24px rgba(37,99,235,0.12)',
      },
      keyframes: {
        'glass-float': {
          '0%,100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-6px)' },
        },
        'glass-pulse': {
          '0%,100%': { opacity: '1' },
          '50%': { opacity: '0.55' },
        },
        'particle-drift': {
          '0%': { transform: 'translateX(0) translateY(0)', opacity: '0' },
          '10%': { opacity: '0.8' },
          '100%': { transform: 'translateX(40px) translateY(-30px)', opacity: '0' },
        },
        sheen: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
      animation: {
        'glass-float': 'glass-float 6s ease-in-out infinite',
        'glass-pulse': 'glass-pulse 2.4s ease-in-out infinite',
        'particle-drift': 'particle-drift 4s linear infinite',
        sheen: 'sheen 2.5s linear infinite',
      },
    },
  },
  plugins: [],
};
