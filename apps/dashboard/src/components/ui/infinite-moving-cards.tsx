import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export interface MovingCardItem {
	quote: string;
	name: string;
	title: string;
}

interface InfiniteMovingCardsProps {
	items: MovingCardItem[];
	direction?: "left" | "right";
	speed?: "fast" | "normal" | "slow";
	className?: string | undefined;
}

const SPEED_MS: Record<NonNullable<InfiniteMovingCardsProps["speed"]>, string> = {
	fast: "26s",
	normal: "44s",
	slow: "70s",
};

/**
 * Edge-faded, hover-pausing marquee of testimonial cards (CSS-only animation).
 * Duplicates the list once for a seamless loop. Honors prefers-reduced-motion
 * via the `.infinite-cards-track` rule in index.css (animation disabled).
 */
export function InfiniteMovingCards({
	items,
	direction = "left",
	speed = "slow",
	className,
}: InfiniteMovingCardsProps) {
	const containerRef = useRef<HTMLDivElement>(null);
	const [started, setStarted] = useState(false);

	useEffect(() => {
		setStarted(true);
	}, []);

	return (
		<div
			ref={containerRef}
			className={cn(
				"infinite-cards relative z-10 w-full overflow-hidden",
				"[mask-image:linear-gradient(to_right,transparent,black_12%,black_88%,transparent)]",
				className,
			)}
		>
			<ul
				className={cn(
					"infinite-cards-track flex min-w-full shrink-0 flex-nowrap items-stretch gap-4 py-1",
					started && "is-animated",
				)}
				style={{
					["--infinite-cards-duration" as string]: SPEED_MS[speed],
					["--infinite-cards-direction" as string]:
						direction === "left" ? "forwards" : "reverse",
				}}
			>
				{[...items, ...items].map((item, index) => (
					<li
						key={`${item.name}-${index}`}
						className="relative w-[20rem] max-w-full shrink-0 rounded-2xl border border-border bg-card p-5 shadow-sm sm:w-[22rem]"
					>
						<p className="text-sm leading-6 text-foreground">“{item.quote}”</p>
						<div className="mt-4 flex items-center gap-3">
							<span className="grid size-8 place-items-center rounded-full bg-[color-mix(in_srgb,var(--color-primary)_14%,var(--color-card))] text-xs font-semibold text-primary">
								{item.name.slice(0, 1)}
							</span>
							<div className="min-w-0">
								<p className="truncate text-sm font-semibold text-foreground">
									{item.name}
								</p>
								<p className="truncate text-xs text-muted-foreground">
									{item.title}
								</p>
							</div>
						</div>
					</li>
				))}
			</ul>
		</div>
	);
}
