/** @type {import('tailwindcss').Config} */
var config = {
  content: ["./app/**/*.{js,jsx}", "./components/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        void: "#0B0E14",
        panel: "#111623",
        "panel-2": "#161C2C",
        seam: "#222B40",
        "seam-bright": "#313D5A",
        phosphor: "#E8EDF7",
        dim: "#8B95AA",
        faint: "#5A6377",
        signal: "#FFB224",
        live: "#3DDC97",
        alert: "#FF5C5C",
        soul: "#B98CFF",
      },
      fontFamily: {
        display: ["var(--font-archivo)", "system-ui", "sans-serif"],
        mono: ["var(--font-spline-sans-mono)", "SF Mono", "monospace"],
      },
      borderRadius: {
        panel: "10px",
      },
    },
  },
  plugins: [],
};

export default config;
