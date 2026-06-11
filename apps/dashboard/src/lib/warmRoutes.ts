// Pre-parse the chunks for the routes an authed operator is most likely
// to hit first, during the browser's idle window. Vite emits each
// `React.lazy(() => import(...))` call as its own hashed chunk; static
// <link rel="modulepreload"> in index.html would need a post-build hash
// injection step. Issuing the dynamic import here achieves the same
// "chunk parsed + compiled before navigation" effect without fighting
// the bundler — Vite dedups the module graph, so when Suspense later
// resolves the same import, it reuses the already-fetched promise.
//
// Order matches the highest-probability operator flow. Keep this list short:
// warming every authenticated route quietly downloads large editor/chart
// chunks and turns "faster navigation" into an unnecessary memory/network tax.

const HOT_ROUTE_IMPORTS: Array<() => Promise<unknown>> = [
	() => import("../pages/Dashboard"),
	() => import("../pages/Analytics"),
	() => import("../pages/Calendar"),
	() => import("../pages/Composer"),
];

export function warmHotRoutes(): void {
	if (typeof window === "undefined") return;

	// In dev, every dynamic import can trigger Vite transforms and module
	// evaluation. Warming every route makes localhost sluggish, but leaving
	// Analytics cold is exactly why switching to the paid analytics surface
	// feels amateur during QA. Warm just Analytics in dev; production warms
	// the full operator path below.
	if (import.meta.env.DEV) {
		const warmAnalytics = () => {
			if (window.location.pathname === "/analytics") return;
			void import("../pages/Analytics").catch(() => {});
		};
		const idle = (
				window as Window & {
					requestIdleCallback?: (
	                    					callback: () => void,
	                    					opts?: { timeout: number },
	                    				) => number | undefined;
				}
		).requestIdleCallback;
		if (idle) idle(warmAnalytics, { timeout: 4000 });
		else setTimeout(warmAnalytics, 2500);
		return;
	}

	let index = 0;
	const scheduleIdle = (cb: () => void) => {
		const idle = (
				window as Window & {
					requestIdleCallback?: (
	                    					callback: () => void,
	                    					opts?: { timeout: number },
	                    				) => number | undefined;
			}
		).requestIdleCallback;
		if (idle) idle(cb, { timeout: 3000 });
		else setTimeout(cb, 2000);
	};

	const runNext = () => {
		const load = HOT_ROUTE_IMPORTS[index];
		index += 1;
		if (!load) return;

		// Swallow rejections — a chunk fetch failure here is non-fatal;
		// the real import() on navigation will surface any error.
		void load()
			.catch(() => {})
			.finally(() => {
				if (index < HOT_ROUTE_IMPORTS.length) scheduleIdle(runNext);
			});
	};

	// Wait until after first paint so the warmup never contends with
	// critical-path rendering. Load one route per idle slice so a warmup
	// pass does not monopolize the main thread.
	scheduleIdle(runNext);
}
