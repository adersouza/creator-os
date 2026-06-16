import type React from "react";
import { cn } from "@/lib/utils";

export function MarketingShell({ children }: { children: React.ReactNode }) {
	return (
		<div className="landing-shell min-h-screen overflow-x-clip bg-[var(--color-surface-frame)] text-foreground">
			{children}
		</div>
	);
}

export function MarketingContainer({
	children,
	className,
}: {
	children: React.ReactNode;
	className?: string | undefined;
}) {
	return (
		<div className={cn("mx-auto w-full max-w-[1520px] px-5 sm:px-8 lg:px-10", className)}>
			{children}
		</div>
	);
}

export function HeroBeams() {
	return (
		<div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
			<div className="landing-grid absolute inset-0 opacity-70" />
			<div className="landing-spotlight absolute -right-[12%] top-0 h-[42rem] w-[54rem] rounded-full blur-3xl" />
			<div className="landing-beam landing-beam-a absolute right-[11%] top-0 h-[44rem] w-1 rotate-[32deg] rounded-full" />
			<div className="landing-beam landing-beam-b absolute right-[24%] top-10 h-[37rem] w-1 rotate-[32deg] rounded-full" />
			<div className="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-b from-transparent to-[var(--color-surface-frame)]" />
		</div>
	);
}

export function BorderBeam({ className }: { className?: string | undefined }) {
	return (
		<span
			aria-hidden="true"
			className={cn(
				"landing-border-beam pointer-events-none absolute inset-0 rounded-[inherit]",
				className,
			)}
		/>
	);
}

export function SpotlightCard({
	children,
	className,
}: {
	children: React.ReactNode;
	className?: string | undefined;
}) {
	return (
		<div className={cn("landing-spotlight-card group relative overflow-hidden rounded-2xl border border-border bg-card text-card-foreground shadow-sm", className)}>
			<div className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100" aria-hidden="true">
				<div className="absolute -right-10 -top-10 size-40 rounded-full bg-[color-mix(in_srgb,var(--color-primary)_12%,transparent)] blur-2xl" />
			</div>
			{children}
		</div>
	);
}

export function LogoMarquee({
	children,
	reverse = false,
}: {
	children: React.ReactNode;
	reverse?: boolean | undefined;
}) {
	return (
		<div className="relative overflow-hidden">
			<div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-16 bg-gradient-to-r from-[var(--color-surface-frame)] to-transparent" />
			<div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-16 bg-gradient-to-l from-[var(--color-surface-frame)] to-transparent" />
			<div className={cn("landing-marquee flex min-w-max items-center gap-3", reverse && "landing-marquee-reverse")}>
				{children}
				{children}
			</div>
		</div>
	);
}

export function WorkflowBeam() {
	return (
		<svg
			className="pointer-events-none absolute inset-0 hidden h-full w-full lg:block"
			viewBox="0 0 1200 360"
			fill="none"
			aria-hidden="true"
			preserveAspectRatio="none"
		>
			<path
				d="M120 180 C 260 70, 370 70, 500 180 S 750 290, 880 180 S 1060 70, 1120 180"
				stroke="url(#landing-workflow-gradient)"
				strokeWidth="2"
				strokeDasharray="8 10"
				className="landing-flow-path"
			/>
			<defs>
				<linearGradient id="landing-workflow-gradient" x1="80" x2="1120" y1="180" y2="180">
					<stop stopColor="var(--color-border)" />
					<stop offset="0.5" stopColor="var(--color-primary)" />
					<stop offset="1" stopColor="var(--color-border)" />
				</linearGradient>
			</defs>
		</svg>
	);
}
