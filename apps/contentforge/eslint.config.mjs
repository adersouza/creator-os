import nextVitals from "eslint-config-next/core-web-vitals";

var config = [
  {
    ignores: [
      ".next/**",
      ".venv/**",
      "node_modules/**",
      "output/**",
      "uploads/**",
      "public/thumbnails/**",
    ],
  },
  ...nextVitals,
  {
    ignores: [
      ".next/**",
      ".venv/**",
      "node_modules/**",
      "output/**",
      "uploads/**",
      "public/thumbnails/**",
    ],
    rules: {
      "@next/next/no-img-element": "off",
      "@next/next/no-page-custom-font": "off",
      "react-hooks/set-state-in-effect": "off",
    },
  },
];

export default config;
