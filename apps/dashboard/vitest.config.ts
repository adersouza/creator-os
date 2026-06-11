import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

// More info at: https://storybook.js.org/docs/next/writing-tests/integrations/vitest-addon
export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.{test,spec}.{ts,tsx}", "src/**/*.{test,spec}.{ts,tsx}"],
    exclude: ["node_modules", "dist", "e2e"],
    coverage: {
      provider: "v8",
      reportOnFailure: true,
      reporter: ["text", "json", "html"],
      exclude: ["node_modules", "tests", "**/*.d.ts", "**/*.config.*", "api/cron/**", "api/admin/**", "api/auth/**"],
      thresholds: {
        // Ratchet up as coverage improves — never lower these
        statements: 38,
        branches: 31,
        functions: 38,
        lines: 39,
      },
    },
  },
  resolve: {
    alias: [
      { find: /^@\/api(?=\/|$)/, replacement: path.resolve(__dirname, "./api") },
      { find: "@/src", replacement: path.resolve(__dirname, "./src") },
      { find: "@/components", replacement: path.resolve(__dirname, "./src/components") },
      { find: "@/contexts", replacement: path.resolve(__dirname, "./src/contexts") },
      { find: "@/data", replacement: path.resolve(__dirname, "./src/data") },
      { find: "@/hooks", replacement: path.resolve(__dirname, "./src/hooks") },
      { find: "@/lib", replacement: path.resolve(__dirname, "./src/lib") },
      { find: "@/pages", replacement: path.resolve(__dirname, "./src/pages") },
      { find: "@/services", replacement: path.resolve(__dirname, "./src/services") },
      { find: "@/stores", replacement: path.resolve(__dirname, "./src/stores") },
      { find: "@/test", replacement: path.resolve(__dirname, "./src/test") },
      { find: "@/types", replacement: path.resolve(__dirname, "./src/types") },
      { find: "@/utils", replacement: path.resolve(__dirname, "./src/utils") },
      { find: "@", replacement: path.resolve(__dirname, "./src") },
    ],
  }
});
