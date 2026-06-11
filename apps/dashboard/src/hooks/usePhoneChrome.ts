import { useEffect, useState } from "react";

const buildPhoneChromeQuery = (max: number) =>
	`(max-width: ${max}px) and (pointer: coarse) and (hover: none)`;

/**
 * Returns true only on actual touch devices (phones / iPads in tablet mode)
 * with viewport ≤ `maxWidth`. Desktop browsers — even when resized narrow —
 * report `pointer: fine` and `hover: hover`, so they never trigger mobile
 * chrome. This prevents the "desktop window dragged narrow → mobile UI"
 * regression.
 */
export function usePhoneChrome(maxWidth = 767): boolean {
	const getMatch = () => {
		if (typeof window === "undefined") return false;
		return window.matchMedia(buildPhoneChromeQuery(maxWidth)).matches;
	};

	const [matches, setMatches] = useState(getMatch);

	useEffect(() => {
		if (typeof window === "undefined") return;
		const mql = window.matchMedia(buildPhoneChromeQuery(maxWidth));
		const update = () => setMatches(mql.matches);
		update();
		mql.addEventListener("change", update);
		window.addEventListener("resize", update);
		return () => {
			mql.removeEventListener("change", update);
			window.removeEventListener("resize", update);
		};
	}, [maxWidth]);

	return matches;
}
