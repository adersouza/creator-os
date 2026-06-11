import { type RefObject, useEffect, useRef, useState } from "react";

interface PullToRefreshOptions {
	onRefresh: () => unknown | Promise<unknown>;
	threshold?: number | undefined;
	disabled?: boolean | undefined;
	/**
	 * If provided, listens on the element. Otherwise listens on window and
	 * uses `window.scrollY` as the scrollTop reference (page-level scroll).
	 */
	containerRef?: RefObject<HTMLElement | null> | undefined;
}

/**
 * Pull-to-refresh gesture for either a scroll container or the document root.
 *
 * Returns `{ isPulling, pullDistance, isRefreshing }` so the caller can render
 * a translateY indicator. The gesture only engages when scrollTop is 0 and the
 * touch drag is downward — otherwise the browser's native scrolling is
 * unaffected.
 */
export function usePullToRefresh({
	onRefresh,
	threshold = 80,
	disabled = false,
	containerRef,
}: PullToRefreshOptions) {
	const [isPulling, setIsPulling] = useState(false);
	const [pullDistance, setPullDistance] = useState(0);
	const [isRefreshing, setIsRefreshing] = useState(false);
	const startY = useRef(0);
	const pulling = useRef(false);
	const pullDistanceRef = useRef(0);
	const onRefreshRef = useRef(onRefresh);
	const mountedRef = useRef(true);
	onRefreshRef.current = onRefresh;

	useEffect(() => {
		mountedRef.current = true;
		return () => {
			mountedRef.current = false;
		};
	}, []);

	useEffect(() => {
		if (disabled) return;
		if (typeof window === "undefined") return;

		const target: EventTarget = containerRef?.current ?? window;
		const getScrollTop = () =>
			containerRef?.current ? containerRef.current.scrollTop : window.scrollY;

		const onTouchStart = (e: Event) => {
			const te = e as TouchEvent;
			if (getScrollTop() > 0) return;
			const touch = te.touches[0];
			if (!touch) return;
			startY.current = touch.clientY;
			pulling.current = true;
		};

		const onTouchMove = (e: Event) => {
			if (!pulling.current) return;
			const te = e as TouchEvent;
			const touch = te.touches[0];
			if (!touch) return;
			const dy = touch.clientY - startY.current;
			if (dy > 0) {
				const dampened = Math.min(dy * 0.5, 150);
				pullDistanceRef.current = dampened;
				setPullDistance(dampened);
				setIsPulling(true);
				if (dy > 10 && te.cancelable) te.preventDefault();
			} else {
				pullDistanceRef.current = 0;
				setPullDistance(0);
				setIsPulling(false);
			}
		};

		const onTouchEnd = () => {
			if (!pulling.current) return;
			pulling.current = false;
			if (pullDistanceRef.current >= threshold) {
				setIsRefreshing(true);
				pullDistanceRef.current = 0;
				setPullDistance(0);
				setIsPulling(false);
				Promise.resolve()
					.then(() => onRefreshRef.current())
					.catch(() => {
						// Refresh failures are surfaced by the underlying data hooks.
						// The gesture should still settle without leaking an unhandled
						// promise rejection to the browser.
					})
					.finally(() => {
						if (mountedRef.current) setIsRefreshing(false);
					});
			} else {
				pullDistanceRef.current = 0;
				setPullDistance(0);
				setIsPulling(false);
			}
		};

		target.addEventListener("touchstart", onTouchStart, { passive: true });
		// touchmove must NOT be passive so we can preventDefault to suppress
		// iOS rubber-band overscroll on the gesture window.
		target.addEventListener("touchmove", onTouchMove, { passive: false });
		target.addEventListener("touchend", onTouchEnd, { passive: true });
		target.addEventListener("touchcancel", onTouchEnd, { passive: true });

		return () => {
			target.removeEventListener("touchstart", onTouchStart);
			target.removeEventListener("touchmove", onTouchMove);
			target.removeEventListener("touchend", onTouchEnd);
			target.removeEventListener("touchcancel", onTouchEnd);
		};
	}, [containerRef, disabled, threshold]);

	return { isPulling, pullDistance, isRefreshing };
}
