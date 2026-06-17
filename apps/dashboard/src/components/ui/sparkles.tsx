import { useEffect, useMemo, useState } from "react";
import Particles, { initParticlesEngine } from "@tsparticles/react";
import type { ISourceOptions } from "@tsparticles/engine";
import { loadSlim } from "@tsparticles/slim";
import { cn } from "@/lib/utils";

interface SparklesProps {
	id?: string;
	className?: string | undefined;
	/** Particle color. Defaults to an oxblood tint to match the Juno33 brand. */
	color?: string;
	/** Background behind the particle field (usually transparent over a section). */
	background?: string;
	minSize?: number;
	maxSize?: number;
	/** Particles per area — keep low on a marketing hero for LCP. */
	density?: number;
	/** Max opacity of particles. */
	opacity?: number;
}

/**
 * Oxblood-tinted ambient sparkle field for the landing hero.
 *
 * Heavy (tsparticles) — import this lazily and render behind static content so
 * the hero paints first. Renders nothing when the user prefers reduced motion.
 */
export function Sparkles({
	id = "landing-sparkles",
	className,
	color = "#b0405a",
	background = "transparent",
	minSize = 0.4,
	maxSize = 1.1,
	density = 38,
	opacity = 0.5,
}: SparklesProps) {
	const [ready, setReady] = useState(false);
	const [reducedMotion, setReducedMotion] = useState(false);

	useEffect(() => {
		if (
			typeof window !== "undefined" &&
			window.matchMedia("(prefers-reduced-motion: reduce)").matches
		) {
			setReducedMotion(true);
			return;
		}
		let active = true;
		initParticlesEngine(async (engine) => {
			await loadSlim(engine);
		}).then(() => {
			if (active) setReady(true);
		});
		return () => {
			active = false;
		};
	}, []);

	const options = useMemo<ISourceOptions>(
		() => ({
			background: { color: { value: background } },
			fullScreen: { enable: false },
			fpsLimit: 60,
			particles: {
				color: { value: color },
				move: {
					enable: true,
					direction: "none",
					speed: 0.25,
					straight: false,
					outModes: { default: "out" },
				},
				number: { density: { enable: true }, value: density },
				opacity: {
					value: { min: 0.1, max: opacity },
					animation: { enable: true, speed: 1.2, sync: false },
				},
				shape: { type: "circle" },
				size: { value: { min: minSize, max: maxSize } },
			},
			detectRetina: true,
		}),
		[background, color, density, maxSize, minSize, opacity],
	);

	if (reducedMotion || !ready) return null;

	return (
		<Particles id={id} options={options} className={cn("h-full w-full", className)} />
	);
}
