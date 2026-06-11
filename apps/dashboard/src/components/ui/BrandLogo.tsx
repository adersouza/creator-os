import type React from "react";
import { cn } from "@/lib/utils";

export type BrandLogoName =
	| "anthropic"
	| "github"
	| "google"
	| "instagram"
	| "meta"
	| "openai"
	| "posthog"
	| "stripe"
	| "supabase"
	| "threads"
	| "vercel";

export interface BrandLogoProps extends React.HTMLAttributes<HTMLSpanElement> {
	name: BrandLogoName;
	size?: "xs" | "sm" | "md" | "lg" | undefined;
	label?: string | undefined;
	monochrome?: boolean | undefined;
}

const BRAND_LABEL: Record<BrandLogoName, string> = {
	anthropic: "Anthropic",
	github: "GitHub",
	google: "Google",
	instagram: "Instagram",
	meta: "Meta",
	openai: "OpenAI",
	posthog: "PostHog",
	stripe: "Stripe",
	supabase: "Supabase",
	threads: "Threads",
	vercel: "Vercel",
};

const SIZE_CLASS: Record<NonNullable<BrandLogoProps["size"]>, string> = {
	xs: "size-4",
	sm: "size-5",
	md: "size-6",
	lg: "size-8",
};

export function BrandLogo({
	name,
	size = "md",
	label,
	monochrome = false,
	className,
	...props
}: BrandLogoProps) {
	const accessibleLabel = label ?? BRAND_LABEL[name];

	return (
		<span
			role="img"
			aria-label={accessibleLabel}
			className={cn(
				"inline-flex shrink-0 items-center justify-center text-foreground",
				SIZE_CLASS[size],
				className,
			)}
			{...props}
		>
			<BrandMark name={name} monochrome={monochrome} />
		</span>
	);
}

export const IntegrationLogo = BrandLogo;

function brandFill(color: string, monochrome: boolean) {
	return monochrome ? "currentColor" : color;
}

function BrandMark({
	name,
	monochrome,
}: {
	name: BrandLogoName;
	monochrome: boolean;
}) {
	switch (name) {
		case "instagram":
			return (
				<svg viewBox="0 0 24 24" className="size-full" aria-hidden="true">
					<defs>
						<linearGradient id="juno-instagram-gradient" x1="3" x2="21" y1="21" y2="3">
							<stop stopColor="#FEDA75" />
							<stop offset="0.35" stopColor="#FA7E1E" />
							<stop offset="0.62" stopColor="#D62976" />
							<stop offset="1" stopColor="#4F5BD5" />
						</linearGradient>
					</defs>
					<rect
						x="3"
						y="3"
						width="18"
						height="18"
						rx="5"
						fill={monochrome ? "none" : "url(#juno-instagram-gradient)"}
						stroke={monochrome ? "currentColor" : "none"}
						strokeWidth="1.7"
					/>
					<circle cx="12" cy="12" r="4.1" fill="none" stroke={monochrome ? "currentColor" : "white"} strokeWidth="1.8" />
					<circle cx="17.1" cy="6.9" r="1.2" fill={monochrome ? "currentColor" : "white"} />
				</svg>
			);
		case "threads":
			return (
				<svg viewBox="0 0 24 24" className="size-full" aria-hidden="true">
					<circle cx="12" cy="12" r="10" fill={monochrome ? "none" : "#050505"} stroke="currentColor" strokeOpacity="0.12" />
					<path
						d="M15.7 11.2c-.2-3-1.9-4.7-4.5-4.7-2.8 0-4.7 2-4.7 5.4 0 3.6 2.1 5.6 5.4 5.6 2.3 0 4.1-1 4.8-2.8.8-2-.5-3.8-2.9-4.1-2.3-.3-3.6.7-3.8 2.2-.2 1.2.6 2.2 1.9 2.2 1.5 0 2.5-.9 2.6-2.3"
						fill="none"
						stroke={monochrome ? "currentColor" : "white"}
						strokeLinecap="round"
						strokeWidth="1.7"
					/>
				</svg>
			);
		case "meta":
			return (
				<svg viewBox="0 0 24 24" className="size-full" aria-hidden="true">
					<path
						d="M3.5 14.2c1.3-5.2 3.1-7.8 5.5-7.8 1.6 0 2.7 1 4.1 3.2 1.3-2.2 2.5-3.2 4.1-3.2 2.3 0 3.4 2.3 3.2 5.4-.2 3-1.5 5.4-3.4 5.4-1.5 0-2.5-1-4.1-3.8-1.7 2.8-2.8 3.8-4.3 3.8-1.8 0-3.2-1.2-5.1-3Z"
						fill="none"
						stroke={brandFill("#0668E1", monochrome)}
						strokeLinecap="round"
						strokeLinejoin="round"
						strokeWidth="1.9"
					/>
				</svg>
			);
		case "google":
			return (
				<svg viewBox="0 0 24 24" className="size-full" aria-hidden="true">
					<path d="M21 12.2c0-.7-.1-1.3-.2-1.9H12v3.6h5.1a4.4 4.4 0 0 1-1.9 2.9v2.4h3c1.8-1.6 2.8-4 2.8-7Z" fill={brandFill("#4285F4", monochrome)} />
					<path d="M12 21c2.5 0 4.6-.8 6.2-2.2l-3-2.4c-.8.6-1.9.9-3.2.9-2.4 0-4.4-1.6-5.1-3.8H3.8V16A9 9 0 0 0 12 21Z" fill={brandFill("#34A853", monochrome)} />
					<path d="M6.9 13.5a5.4 5.4 0 0 1 0-3.4V7.6H3.8a9 9 0 0 0 0 8.1l3.1-2.2Z" fill={brandFill("#FBBC05", monochrome)} />
					<path d="M12 6.7c1.4 0 2.6.5 3.6 1.4l2.7-2.7A9 9 0 0 0 3.8 7.6L6.9 10c.7-2.1 2.7-3.3 5.1-3.3Z" fill={brandFill("#EA4335", monochrome)} />
				</svg>
			);
		case "github":
			return (
				<svg viewBox="0 0 24 24" className="size-full" aria-hidden="true">
					<path
						d="M12 2.7a9.3 9.3 0 0 0-2.9 18.1c.5.1.7-.2.7-.5v-1.8c-2.9.6-3.5-1.2-3.5-1.2-.5-1.1-1.1-1.4-1.1-1.4-.9-.6.1-.6.1-.6 1 0 1.6 1.1 1.6 1.1.9 1.5 2.4 1.1 2.9.8.1-.7.3-1.1.6-1.4-2.3-.3-4.7-1.2-4.7-5.2 0-1.1.4-2.1 1.1-2.8-.1-.3-.5-1.4.1-2.8 0 0 .9-.3 2.9 1.1.8-.2 1.7-.3 2.6-.3.9 0 1.8.1 2.6.3 2-1.4 2.9-1.1 2.9-1.1.6 1.4.2 2.5.1 2.8.7.8 1.1 1.7 1.1 2.8 0 4-2.4 4.9-4.7 5.2.4.3.7 1 .7 2v2.9c0 .3.2.6.7.5A9.3 9.3 0 0 0 12 2.7Z"
						fill="currentColor"
					/>
				</svg>
			);
		case "stripe":
			return <Wordmark text="S" color="#635BFF" monochrome={monochrome} />;
		case "supabase":
			return (
				<svg viewBox="0 0 24 24" className="size-full" aria-hidden="true">
					<path d="M13.3 2.8 5.4 13.1c-.5.7 0 1.7.9 1.7h5.2l-.8 6.4c-.1.9 1 1.3 1.5.6l6.4-10.4c.4-.7-.1-1.6-.9-1.6h-4.6l1.9-6.4c.3-.9-1.1-1.4-1.7-.6Z" fill={brandFill("#3ECF8E", monochrome)} />
				</svg>
			);
		case "vercel":
			return (
				<svg viewBox="0 0 24 24" className="size-full" aria-hidden="true">
					<path d="M12 4 22 20H2L12 4Z" fill="currentColor" />
				</svg>
			);
		case "openai":
			return <Rosette color="#10A37F" monochrome={monochrome} />;
		case "anthropic":
			return <Wordmark text="A" color="#D4A27F" monochrome={monochrome} />;
		case "posthog":
			return <Wordmark text="P" color="#F54E00" monochrome={monochrome} />;
	}
}

function Wordmark({
	text,
	color,
	monochrome,
}: {
	text: string;
	color: string;
	monochrome: boolean;
}) {
	return (
		<svg viewBox="0 0 24 24" className="size-full" aria-hidden="true">
			<rect x="3" y="3" width="18" height="18" rx="5" fill={brandFill(color, monochrome)} />
			<text x="12" y="16" textAnchor="middle" fontSize="11" fontWeight="700" fill={monochrome ? "var(--color-background)" : "white"}>
				{text}
			</text>
		</svg>
	);
}

function Rosette({
	color,
	monochrome,
}: {
	color: string;
	monochrome: boolean;
}) {
	return (
		<svg viewBox="0 0 24 24" className="size-full" aria-hidden="true">
			{Array.from({ length: 6 }).map((_, index) => (
				<ellipse
					key={index}
					cx="12"
					cy="12"
					rx="3.2"
					ry="8"
					fill="none"
					stroke={brandFill(color, monochrome)}
					strokeWidth="1.4"
					transform={`rotate(${index * 30} 12 12)`}
				/>
			))}
			<circle cx="12" cy="12" r="2.4" fill={brandFill(color, monochrome)} />
		</svg>
	);
}
