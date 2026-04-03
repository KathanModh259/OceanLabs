/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#0a0a0a',
        surface: '#111111',
        primary: '#FF477E', // Beautiful vibrant pink for high-end feel
        secondary: '#00F0FF', // Cyan accent
      }
    },
  },
  plugins: [],
}
