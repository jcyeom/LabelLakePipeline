/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: { 50: '#f0f9ff', 500: '#0ea5e9', 600: '#0284c7', 900: '#0c4a6e' },
        drift: { normal: '#22c55e', warning: '#f59e0b', critical: '#ef4444', republish: '#dc2626' },
        label: { l1: '#6366f1', l2: '#0ea5e9', l3: '#10b981' },
      },
    },
  },
  plugins: [],
}
