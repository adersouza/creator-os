/** @type {import('tailwindcss').Config} */
var config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: "#06060a",
        card: "#0f0f14",
        "card-hover": "#141419",
        border: "#1c1c24",
        "border-hover": "#2a2a36",
        purple: {
          DEFAULT: "#a855f7",
          dim: "#a855f740",
          glow: "#a855f720",
        },
        green: {
          DEFAULT: "#22c55e",
          dim: "#22c55e40",
        },
        amber: {
          DEFAULT: "#eab308",
          dim: "#eab30840",
        },
        muted: "#52525b",
        "muted-dark": "#3a3a46",
        "muted-darker": "#2a2a36",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "SF Mono", "Fira Code", "monospace"],
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        serif: ["Instrument Serif", "Georgia", "serif"],
      },
      borderRadius: {
        card: "12px",
      },
      animation: {
        pulse: "pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "progress-glow": "progress-glow 2s ease-in-out infinite",
      },
      keyframes: {
        "progress-glow": {
          "0%, 100%": { opacity: 0.8 },
          "50%": { opacity: 1 },
        },
      },
    },
  },
  plugins: [],
};

export default config;
