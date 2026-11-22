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
          bg: "#f7f8fa",
          surface: "#ffffff",
          surfaceAlt: "#edf0f2",
          border: "#d3d8dd",
          borderStrong: "#8a949e",
          text: "#181c20",
          muted: "#53606b",
          accent: "#09654b",
          warn: "#875100",
          crit: "#ae2832",
          grid: "#dce1e4",
        },
        background: "#f7f8fa",
        foreground: "#181c20",
        card: { DEFAULT: "#ffffff", foreground: "#181c20" },
        popover: { DEFAULT: "#ffffff", foreground: "#181c20" },
        primary: { DEFAULT: "#202529", foreground: "#ffffff" },
        secondary: { DEFAULT: "#edf0f2", foreground: "#181c20" },
        muted: { DEFAULT: "#edf0f2", foreground: "#53606b" },
        accent: { DEFAULT: "#202529", foreground: "#ffffff" },
        destructive: { DEFAULT: "#ae2832", foreground: "#ffffff" },
        border: "#d3d8dd",
        input: "#d3d8dd",
        ring: "#09654b",
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
