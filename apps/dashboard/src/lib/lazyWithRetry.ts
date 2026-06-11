/**
 * lazyWithRetry — wraps React.lazy() with automatic page reload on chunk load failure.
 * After a deploy, old chunk hashes no longer exist. This catches the import error,
 * reloads the page once (which fetches the new index.html with correct hashes),
 * and only throws on a second consecutive failure.
 */
import { type ComponentType, type LazyExoticComponent, lazy } from "react";

const CHUNK_RELOAD_KEY = "chunk_reload";

// React.lazy itself is typed around ComponentType<any>; keep that looseness
// inside this wrapper while preserving each route component's inferred props.
// biome-ignore lint/suspicious/noExplicitAny: mirrors React.lazy's component constraint.
export function lazyWithRetry<C extends ComponentType<any>>(
	importFn: () => Promise<{ default: C }>,
): LazyExoticComponent<C> {
	return lazy(() =>
		importFn()
			.then((m) => {
				try {
					sessionStorage.removeItem(CHUNK_RELOAD_KEY);
				} catch {
					// Storage can be unavailable in private contexts; the import still succeeded.
				}
				return m;
			})
			.catch((err: Error) => {
				let hasReloaded: string | null = null;
				try {
					hasReloaded = sessionStorage.getItem(CHUNK_RELOAD_KEY);
				} catch {
					hasReloaded = null;
				}
				if (!hasReloaded) {
					try {
						sessionStorage.setItem(CHUNK_RELOAD_KEY, "1");
					} catch {
						// If the marker cannot be stored, a one-time reload is still the best recovery.
					}
					window.location.reload();
					return new Promise(() => {}); // never resolves — page is reloading
				}
				try {
					sessionStorage.removeItem(CHUNK_RELOAD_KEY);
				} catch {
					// Fall through to the error boundary on repeated failure.
				}
				throw err; // let error boundary handle it on second failure
			}),
	) as LazyExoticComponent<C>;
}
