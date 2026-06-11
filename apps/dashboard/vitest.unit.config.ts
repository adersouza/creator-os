import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";
import { fileURLToPath } from "node:url";

const dirname =
	typeof __dirname !== "undefined"
		? __dirname
		: path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
	plugins: [react()],
	test: {
		globals: true,
		environment: "jsdom",
		setupFiles: ["./tests/setup.ts"],
		include: ["**/*.{test,spec}.{ts,tsx}"],
		exclude: ["node_modules", "dist", "e2e"],
	},
	resolve: {
		alias: [
			{ find: /^@\/api(?=\/|$)/, replacement: path.resolve(dirname, "./api") },
			{ find: "@", replacement: path.resolve(dirname, "./src") },
		],
	},
});
