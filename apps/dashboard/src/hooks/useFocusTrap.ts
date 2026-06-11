// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE_SELECTOR =
	'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function useFocusTrap<T extends HTMLElement = HTMLDivElement>(
	onClose?: () => void,
	active = true,
): RefObject<T | null> {
	const ref = useRef<T>(null);

	useEffect(() => {
		if (!active) return;
		const container = ref.current;
		if (!container) return;

		const previouslyFocused = document.activeElement as HTMLElement | null;

		// Focus first focusable element
		const focusable =
			container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
		if (focusable.length > 0) {
			focusable[0]!.focus();
		}

		const handleKeyDown = (e: KeyboardEvent) => {
			if (e.key === "Escape" && onClose) {
				e.preventDefault();
				onClose();
				return;
			}

			if (e.key !== "Tab") return;

			const focusableEls =
				container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
			if (focusableEls.length === 0) return;

			const first = focusableEls[0];
			const last = focusableEls[focusableEls.length - 1];

			if (e.shiftKey) {
				if (document.activeElement === first) {
					e.preventDefault();
					last!.focus();
				}
			} else {
				if (document.activeElement === last) {
					e.preventDefault();
					first!.focus();
				}
			}
		};

		document.addEventListener("keydown", handleKeyDown);
		return () => {
			document.removeEventListener("keydown", handleKeyDown);
			if (previouslyFocused && typeof previouslyFocused.focus === "function") {
				previouslyFocused.focus();
			}
		};
	}, [onClose, active]);

	return ref;
}
