import nextVitals from "eslint-config-next/core-web-vitals";

var config = [
  {
    ignores: [".next/**", "node_modules/**"],
  },
  ...nextVitals,
];

export default config;
