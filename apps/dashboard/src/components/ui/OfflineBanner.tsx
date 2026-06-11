import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { WifiOff } from "lucide-react";

/**
 * Fixed top banner that appears when the browser reports it's offline.
 * Auto-dismisses when connectivity returns. Mounted once at app root.
 *
 * Starts subscribed to navigator.onLine + both online/offline events.
 * Does NOT try to ping the server — matches what the spec window can detect.
 */
export function OfflineBanner() {
	const [online, setOnline] = useState<boolean>(() =>
		typeof navigator !== "undefined" ? navigator.onLine : true,
	);

	useEffect(() => {
		const handleOnline = () => setOnline(true);
		const handleOffline = () => setOnline(false);
		window.addEventListener("online", handleOnline);
		window.addEventListener("offline", handleOffline);
		return () => {
			window.removeEventListener("online", handleOnline);
			window.removeEventListener("offline", handleOffline);
		};
	}, []);

	return (
		<AnimatePresence>
			{!online && (
				<motion.div
					role="status"
					aria-live="polite"
					initial={{ opacity: 0, y: -16 }}
					animate={{ opacity: 1, y: 0 }}
					exit={{ opacity: 0, y: -16 }}
					transition={{ duration: 0.4, ease: [0.23, 1, 0.32, 1] }}
					className="fixed left-1/2 -translate-x-1/2 z-[70] flex items-center gap-2.5 h-9 px-4 rounded-full text-[0.78125rem] font-medium"
					style={{
						top: "calc(env(safe-area-inset-top, 0px) + 12px)",
						background:
							"color-mix(in srgb, var(--color-danger) 95%, transparent)",
						color: "#FFFFFF",
						boxShadow:
							"0 8px 24px color-mix(in_srgb,var(--color-foreground)_28%,transparent)",
					}}
				>
					<WifiOff className="w-3.5 h-3.5" aria-hidden="true" />
					You&apos;re offline — changes will sync when reconnected.
				</motion.div>
			)}
		</AnimatePresence>
	);
}
