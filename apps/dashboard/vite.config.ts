import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "path";
import { compression } from "vite-plugin-compression2";
import { VitePWA } from "vite-plugin-pwa";
import { visualizer } from "rollup-plugin-visualizer";
import { defineConfig, loadEnv } from "vite";

const reactCompilerOptions = {
  babel: { plugins: ["babel-plugin-react-compiler"] },
} as Parameters<typeof react>[0];

const QUERY_CACHE_HASH_INPUTS = [
  "src/services/api",
  "src/hooks",
  "src/lib/dashboardQueryRoots.ts",
] as const;

function collectQueryCacheHashFiles(root: string, input: string): string[] {
  const absoluteInput = path.join(root, input);
  if (!existsSync(absoluteInput)) return [];
  const stats = statSync(absoluteInput);

  if (stats.isFile()) {
    return input.endsWith(".ts") ? [absoluteInput] : [];
  }

  return readdirSync(absoluteInput)
    .flatMap((entry) => collectQueryCacheHashFiles(root, path.join(input, entry)))
    .filter((file) => {
      const relative = path.relative(root, file).split(path.sep).join("/");
      return /^src\/services\/api\/[^/]+\.ts$/.test(relative)
        || /^src\/hooks\/use[^/]+\.ts$/.test(relative);
    });
}

function computeQueryCacheHash(root: string): string {
  const files = Array.from(new Set(
    QUERY_CACHE_HASH_INPUTS.flatMap((input) => collectQueryCacheHashFiles(root, input)),
  )).sort();

  const hash = createHash("sha256");
  for (const file of files) {
    hash.update(path.relative(root, file).split(path.sep).join("/"));
    hash.update("\0");
    hash.update(readFileSync(file));
    hash.update("\0");
  }

  return hash.digest("hex").slice(0, 12);
}

export default defineConfig(({ mode, command }) => {
  const env = loadEnv(mode, ".", "");
  const isAnalyze = mode === "analyze";
  const devApiProxyTarget = (env.VITE_DEV_API_PROXY_TARGET || env.VITE_API_BASE_URL || "").replace(/\/+$/, "");
  const shouldProxyApi = /^https?:\/\//i.test(devApiProxyTarget);
  const queryCacheHash = command === "build" ? computeQueryCacheHash(__dirname) : "dev";

  return {
    plugins: [
      react(reactCompilerOptions),
      tailwindcss(),
      {
        // Guard: api/ is Vercel-Function code that imports Node-only deps
        // (@sentry/node, @upstash/*, etc.). If vite's dev server ever tries
        // to transform an api/ file for the browser — triggered by a stray
        // direct request or a misrouted import — it pulls those Node deps
        // into its optimizer and crashes with obscure errors like
        // `Invalid loader value: "5"`. We only block raw file requests
        // (paths ending in .ts/.tsx/.js/.mjs under server-only dirs) so
        // future API proxies or cleanly-routed /api/* calls still pass.
        name: "block-api-dir-from-browser",
        enforce: "pre" as const,
        configureServer(server: import("vite").ViteDevServer) {
          const SERVER_ONLY_FILE = /^\/(api|supabase|scripts)\/.*\.(ts|tsx|mjs|js)(\?|$)/;
          const STALE_AUTOPILOT_CLASSIFIER =
            /^\/api\/_lib\/handlers\/autopilot\/failure-classify\.ts(?:\?|$)/;
          // Also 404 bare /api/* requests unless a dev proxy is configured
          // (e.g. VITE_API_BASE_URL=https://juno33.com). Without either guard,
          // Vite resolves the route to api/analytics.ts and crashes on the
          // file's Node-only imports.
          const API_REQUEST = /^\/api\//;
          server.middlewares.use((req: import("http").IncomingMessage, _res: import("http").ServerResponse, next: () => void) => {
            const url = req.url || "";
            if (STALE_AUTOPILOT_CLASSIFIER.test(url)) {
              _res.statusCode = 200;
              _res.setHeader("Content-Type", "application/javascript; charset=utf-8");
              _res.end(
                "export { classifyFailureReason, normalizeFailureReason } from '/src/lib/autopilotFailureClassify.ts';\n",
              );
              return;
            }
            if (SERVER_ONLY_FILE.test(url) || (API_REQUEST.test(url) && !shouldProxyApi)) {
              _res.statusCode = 404;
              _res.setHeader("Content-Type", "text/plain; charset=utf-8");
              _res.end(
                "Not found — server-only file cannot be served to the browser.",
              );
              return;
            }
            next();
          });
        },
      },
      compression({ algorithms: ["brotliCompress"], exclude: [/\.(br|gz)$/] }),
      compression({ algorithms: ["gzip"], exclude: [/\.(br|gz)$/] }),
      VitePWA({
        strategies: "injectManifest",
        injectRegister: false,
        srcDir: "src",
        filename: "sw.js",
        registerType: "autoUpdate",
        manifest: false,
        injectManifest: {
          swSrc: path.resolve(__dirname, "src/sw.ts"),
          rollupFormat: "iife",
          globPatterns: ["**/*.{js,css,html,woff2,png,svg}"],
          globIgnores: [
            "**/sentry-*.js",
            "**/motion-*.js",
            "**/supabase-*.js",
            // PostHog is dynamically imported only after consent is granted,
            // so precaching wastes 175KB of brotli budget for users who never
            // opt in.
            "**/vendor-posthog-*.js",
            // @google/genai is server-only (used by Vercel Functions); split
            // by manualChunks but never reached from the browser bundle.
            "**/vendor-google-ai-*.js",
          ],
          maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
        },
        devOptions: { enabled: false },
      }),
      isAnalyze &&
        visualizer({
          filename: "dist/stats.html",
          gzipSize: true,
          brotliSize: true,
          template: "treemap",
          open: false,
        }),
    ].filter(Boolean),
    define: {
      "process.env.GEMINI_API_KEY": JSON.stringify(env.GEMINI_API_KEY),
      "import.meta.env.VITE_QUERY_CACHE_HASH": JSON.stringify(queryCacheHash),
    },
    resolve: {
      alias: [
        { find: /^@\/api(?=\/|$)/, replacement: path.resolve(__dirname, "./api") },
        { find: "es-toolkit/compat/get", replacement: path.resolve(__dirname, "./src/lib/recharts-compat/get.js") },
        { find: "es-toolkit/compat/isPlainObject", replacement: path.resolve(__dirname, "./src/lib/recharts-compat/isPlainObject.js") },
        { find: "es-toolkit/compat/last", replacement: path.resolve(__dirname, "./src/lib/recharts-compat/last.js") },
        { find: "es-toolkit/compat/maxBy", replacement: path.resolve(__dirname, "./src/lib/recharts-compat/maxBy.js") },
        { find: "es-toolkit/compat/minBy", replacement: path.resolve(__dirname, "./src/lib/recharts-compat/minBy.js") },
        { find: "es-toolkit/compat/omit", replacement: path.resolve(__dirname, "./src/lib/recharts-compat/omit.js") },
        { find: "es-toolkit/compat/range", replacement: path.resolve(__dirname, "./src/lib/recharts-compat/range.js") },
        { find: "es-toolkit/compat/sortBy", replacement: path.resolve(__dirname, "./src/lib/recharts-compat/sortBy.js") },
        { find: "es-toolkit/compat/sumBy", replacement: path.resolve(__dirname, "./src/lib/recharts-compat/sumBy.js") },
        { find: "es-toolkit/compat/throttle", replacement: path.resolve(__dirname, "./src/lib/recharts-compat/throttle.js") },
        { find: "es-toolkit/compat/uniqBy", replacement: path.resolve(__dirname, "./src/lib/recharts-compat/uniqBy.js") },
        { find: "@", replacement: path.resolve(__dirname, "./src") },
      ],
    },
    server: {
      port: 3000,
      host: "0.0.0.0",
      allowedHosts: [".ngrok-free.app"],
      hmr: process.env.DISABLE_HMR !== "true",
	      proxy: shouldProxyApi
	        ? {
	            "/api": {
              target: devApiProxyTarget,
              changeOrigin: true,
              secure: true,
              configure(proxy) {
                proxy.on("proxyReq", (proxyReq) => {
                  proxyReq.setHeader("origin", devApiProxyTarget);
                  proxyReq.setHeader("referer", `${devApiProxyTarget}/`);
                });
              },
            },
	          }
	        : {},
    },
    build: {
      target: ["chrome92", "firefox95", "safari15", "edge92"],
      chunkSizeWarningLimit: 600,
      reportCompressedSize: false,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes("node_modules")) return;
            if (id.includes("framer-motion") || id.includes("/motion/")) return "motion";
            if (id.includes("@supabase")) return "supabase";
            if (id.includes("isomorphic-dompurify") || id.includes("dompurify")) return "sanitize";
            if (id.includes("lucide-react")) return "icons";
            if (id.includes("@radix-ui")) return "radix";
            if (id.includes("date-fns")) return "dates";
            if (id.includes("@sentry")) return "sentry";
            if (id.includes("@google/genai")) return "vendor-google-ai";
            if (id.includes("posthog-js")) return "vendor-posthog";
            if (id.includes("recharts")) return "charts";
            if (id.includes("@tanstack/react-table")) return "tanstack-table";
            if (id.includes("@tanstack/")) return "react-query";
            if (id.includes("react-router")) return "router";
            if (id.includes("@dnd-kit")) return "dnd";
            if (id.includes("/sonner/") || id.includes("sonner-")) return "sonner";
            if (id.includes("cmdk")) return "cmdk";
          },
        },
      },
    },
    optimizeDeps: {
      include: [
        "react-router-dom",
        "recharts",
        "motion/react",
        "sonner",
        "@tanstack/react-query",
        "@tanstack/react-query-persist-client",
        "@tanstack/query-async-storage-persister",
        "idb-keyval",
        "web-vitals",
        "@supabase/supabase-js",
      ],
    },
  };
});
