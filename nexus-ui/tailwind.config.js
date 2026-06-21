/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Frosted-pastel "Liquid Glass" palette — cream base, soft mint/blush/sky
        // glass tints, periwinkle accent. Light-first; `ink` is the deep-tinted
        // dark-mode floor that keeps the same hue family.
        nexus: {
          accent: '#5b7cfa',        // periwinkle — primary CTA / active
          'accent-soft': '#9db4ff', // lighter periwinkle — glows / hovers
          cream: '#f6f3ec',         // warm off-white app base (light)
          surface: '#ffffff',
          muted: '#6c7078',         // warm-cool gray — secondary text
          border: '#e7e1d4',        // warm hairline divider (on cream)
          ink: '#10131c',           // deep tinted base (dark-mode floor)
          'ink-soft': '#1b2030',    // raised dark surface
          // Pastel glass tints — used for surface veils + 3D sphere materials.
          mint: '#bfe8d4',
          blush: '#f6d4dd',
          sky: '#cfe0f5',
          // Graph/state semantic colors. Also exported as hex from
          // lib/topology.js (Phase 3) for the Canvas graph, which cannot
          // read Tailwind classes — keep these in sync with topology.js.
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
        glass: '30px',      // iOS frosted tier — inline panes/cards
        'glass-xl': '44px', // heavy frost — header, rail, dialog
        '3xl': '40px',
      },
      borderRadius: {
        glass: '1.25rem',     // continuous corner — panes
        'glass-lg': '1.75rem',// continuous corner — cards/dialogs
        'glass-xl': '2rem',   // thick-edge frosted cards (ref 1)
      },
      boxShadow: {
        'glass-sm': '0 1px 2px rgba(15,23,42,0.04), 0 1px 3px rgba(15,23,42,0.06)',
        glass: '0 4px 16px rgba(15,23,42,0.06), 0 2px 4px rgba(15,23,42,0.04)',
        'glass-lg': '0 12px 32px rgba(15,23,42,0.10), 0 4px 8px rgba(15,23,42,0.05)',
        // Liquid Glass: large soft drop for floating surfaces.
        'glass-float': '0 16px 48px rgba(15,23,42,0.12), 0 4px 12px rgba(15,23,42,0.06)',
        // Inset specular top-edge highlight — the iOS "light catches the rim".
        'glass-inset': 'inset 0 1px 0 0 rgba(255,255,255,0.65), inset 0 0 0 1px rgba(255,255,255,0.10)',
        'glass-inset-dark': 'inset 0 1px 0 0 rgba(255,255,255,0.12), inset 0 0 0 1px rgba(255,255,255,0.04)',
        'glass-glow': '0 0 0 1px rgba(10,132,255,0.14), 0 10px 30px rgba(10,132,255,0.18)',
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
        // iOS mount reveal — rise + fade + de-blur.
        'glass-rise': {
          '0%': { opacity: '0', transform: 'translateY(8px) scale(0.985)' },
          '100%': { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
      },
      animation: {
        'glass-float': 'glass-float 6s ease-in-out infinite',
        'glass-pulse': 'glass-pulse 2.4s ease-in-out infinite',
        'particle-drift': 'particle-drift 4s linear infinite',
        sheen: 'sheen 2.5s linear infinite',
        'glass-rise': 'glass-rise 0.32s cubic-bezier(0.22,1,0.36,1)',
      },
    },
  },
  plugins: [],
};
