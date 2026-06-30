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
      // Real-bug rules with zero current violations — enforced.
      "no-undef": "error",
      "no-unreachable": "error",
      // Unused-vars is a 25-item backlog; warn (non-blocking) so it surfaces
      // without a red gate. Underscore-prefixed args are intentional skips.
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
];

export default config;
