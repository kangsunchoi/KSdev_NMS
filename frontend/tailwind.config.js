/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ["./src/**/*.{js,jsx,ts,tsx}", "./public/index.html"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "Menlo", "Consolas", "monospace"],
      },
      colors: {
        nv: {
          bg: "#1a1a2e",
          surface: "#16213e",
          surfaceAlt: "#1f2a4a",
          border: "#2a3b55",
          borderStrong: "#3a4f6f",
          text: "#f8f9fa",
          muted: "#94a3b8",
          accent: "#16c79a",
          warn: "#f4d03f",
          crit: "#e74c3c",
          grid: "#252a40",
        },
        background: "#1a1a2e",
        foreground: "#f8f9fa",
        card: { DEFAULT: "#16213e", foreground: "#f8f9fa" },
        popover: { DEFAULT: "#16213e", foreground: "#f8f9fa" },
        primary: { DEFAULT: "#16c79a", foreground: "#0b1220" },
        secondary: { DEFAULT: "#1f2a4a", foreground: "#f8f9fa" },
        muted: { DEFAULT: "#1f2a4a", foreground: "#94a3b8" },
        accent: { DEFAULT: "#16c79a", foreground: "#0b1220" },
        destructive: { DEFAULT: "#e74c3c", foreground: "#ffffff" },
        border: "#2a3b55",
        input: "#2a3b55",
        ring: "#16c79a",
      },
      borderRadius: {
        lg: "4px",
        md: "3px",
        sm: "2px",
      },
      keyframes: {
        "accordion-down": { from: { height: "0" }, to: { height: "var(--radix-accordion-content-height)" } },
        "accordion-up": { from: { height: "var(--radix-accordion-content-height)" }, to: { height: "0" } },
        "led-pulse": {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.55", transform: "scale(0.92)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "led-pulse": "led-pulse 1.4s ease-in-out infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
