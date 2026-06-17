import { lazy, Suspense, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
	ArrowRight,
	Activity,
	BarChart3,
	CalendarDays,
	Check,
	ChevronDown,
	Eye,
	Gauge,
	Inbox,
	MessageCircle,
	PlayCircle,
	ShieldCheck,
	Sparkles,
	TrendingUp,
	Users,
	Zap,
} from "lucide-react";
import {
	Accordion,
	AccordionContent,
	AccordionItem,
	AccordionTrigger,
} from "@/components/ui/Accordion";
import { AnimatedNumber } from "@/components/ui/AnimatedNumber";
import { Badge } from "@/components/ui/Badge";
import { BentoGrid } from "@/components/ui/bento-grid";
import { BrandLogo, type BrandLogoName } from "@/components/ui/BrandLogo";
import { Button } from "@/components/ui/Button";
import { ContainerScroll } from "@/components/ui/container-scroll-animation";
import {
	InfiniteMovingCards,
	type MovingCardItem,
} from "@/components/ui/infinite-moving-cards";
import { Input } from "@/components/ui/Input";
import {
	HeroBeams,
	LogoMarquee,
	MarketingContainer,
	MarketingShell,
	SpotlightCard,
} from "@/components/landing/LandingEffects";
import { LandingProductMockup } from "@/components/landing/LandingProductMockup";
import { supabaseAuth } from "@/services/supabase";

// Heavy particle field — lazy so the hero paints before tsparticles loads.
const HeroSparkles = lazy(() =>
	import("@/components/ui/sparkles").then((m) => ({ default: m.Sparkles })),
);

const integrationLogos: Array<{ name: BrandLogoName; label: string }> = [
	{ name: "instagram", label: "Instagram" },
	{ name: "threads", label: "Threads" },
	{ name: "stripe", label: "Stripe" },
	{ name: "supabase", label: "Supabase" },
	{ name: "vercel", label: "Vercel" },
	{ name: "posthog", label: "PostHog" },
	{ name: "openai", label: "OpenAI" },
	{ name: "anthropic", label: "Anthropic" },
];

const workflowSteps = [
	{
		title: "Plan",
		description:
			"Build the week across every account and spot gaps before they hit.",
		icon: CalendarDays,
		className: "md:col-span-2",
		preview: "calendar",
	},
	{
		title: "Publish",
		description: "Queue posts, check readiness, and keep approvals moving.",
		icon: Zap,
		className: "md:col-span-1",
		preview: "publish",
	},
	{
		title: "Reply",
		description: "Route the inbox by owner, priority, account, and platform.",
		icon: Inbox,
		className: "md:col-span-1",
		preview: "inbox",
	},
	{
		title: "Learn",
		description: "Turn the top posts and weak signals into tomorrow's plan.",
		icon: BarChart3,
		className: "md:col-span-2",
		preview: "analytics",
	},
] as const;

const analyticsCards = [
	{
		label: "Views",
		value: "512K",
		change: "+8.7%",
		detail: "vs prior window",
		icon: Eye,
		series: [28, 34, 32, 46, 52, 61, 74, 68],
	},
	{
		label: "People reached",
		value: "142K",
		change: "+12.4%",
		detail: "across active scope",
		icon: Activity,
		series: [18, 24, 31, 35, 39, 48, 57, 63],
	},
	{
		label: "Engagement",
		value: "3.6%",
		change: "+0.6 pts",
		detail: "weighted by reach",
		icon: TrendingUp,
		series: [22, 25, 21, 34, 29, 45, 42, 53],
	},
	{
		label: "Waiting for reply",
		value: "24",
		change: "12 urgent",
		detail: "prioritized conversations",
		icon: MessageCircle,
		series: [54, 44, 48, 37, 31, 28, 26, 24],
	},
] as const;

const analyticsBreakdown = [
	{ label: "Threads", value: "58%", color: "var(--color-primary)" },
	{ label: "Instagram", value: "32%", color: "var(--color-chart-3)" },
	{ label: "Inbox-driven", value: "10%", color: "var(--color-chart-5)" },
];

const operationalProof = [
	"Readiness checks run before publishing",
	"Unavailable metrics are explicit, not hidden",
	"Inbox, calendar, and analytics stay connected",
	"Built for account groups and team handoffs",
];

const faqs = [
	{
		question: "Does Juno33 replace my content calendar?",
		answer:
			"Yes. Juno33 gives your team a calendar, composer, approval flow, media handling, and performance readout for Threads and Instagram in one workspace.",
	},
	{
		question: "Can I use it with many accounts?",
		answer:
			"That is the core use case. Juno33 is built around account groups, workspace scope, readiness checks, and performance views that still work when the fleet gets large.",
	},
	{
		question: "Is the inbox connected to analytics?",
		answer:
			"Yes. The inbox stays operational, while the dashboard and analytics surfaces show what changed, what needs a response, and which posts deserve follow-up.",
	},
	{
		question: "What happens after I start free?",
		answer:
			"You can create a workspace, connect accounts, draft posts, and start reviewing the operational surfaces before rolling it out to the full team.",
	},
];

const heroStats = [
	{ value: 8, suffix: "+", label: "platforms & tools connected" },
	{ value: 512, suffix: "K", label: "views tracked per window" },
	{ value: 96, suffix: "%", label: "publish readiness" },
] as const;

const proofStats = [
	{ value: 240, suffix: "+", label: "accounts under management" },
	{ value: 18, suffix: "K", label: "posts shipped" },
	{ value: 99.9, suffix: "%", label: "publish uptime", decimals: 1 },
	{ value: 24, suffix: "/7", label: "inbox coverage" },
] as const;

const testimonials: MovingCardItem[] = [
	{
		quote:
			"We run nine brand accounts from one workspace now. The readiness checks alone killed our double-post problem.",
		name: "Maya R.",
		title: "Head of Social, consumer brand",
	},
	{
		quote:
			"The inbox routing by owner and account is the first tool my team didn't fight. Replies stopped slipping.",
		name: "Devin O.",
		title: "Community Lead, agency",
	},
	{
		quote:
			"Planning the week across Threads and Instagram in one calendar saved us a full day of coordination.",
		name: "Priya S.",
		title: "Content Director",
	},
	{
		quote:
			"Analytics that says when a metric is unavailable instead of faking it. That's why we trust the numbers.",
		name: "Jordan L.",
		title: "Growth, creator studio",
	},
	{
		quote:
			"Account groups and handoffs mean a new operator is productive on day one, not week two.",
		name: "Sam K.",
		title: "Operations Manager",
	},
];

function WorkflowPreview({
	type,
}: {
	type: (typeof workflowSteps)[number]["preview"];
}) {
	if (type === "calendar") {
		return (
			<div
				data-workflow-preview="calendar"
				className="relative h-44 overflow-hidden rounded-xl border border-border bg-muted/45 p-4"
			>
				<div className="mb-3 flex items-center justify-between">
					<div className="h-3 w-28 rounded-full bg-foreground/12" />
					<Badge tone="outline">Week view</Badge>
				</div>
				<div className="grid grid-cols-5 gap-2">
					{["Mon", "Tue", "Wed", "Thu", "Fri"].map((day, index) => (
						<div
							key={day}
							className="min-h-20 rounded-lg border border-border bg-card p-2"
						>
							<p className="text-xs font-semibold text-muted-foreground">
								{day}
							</p>
							<div
								className={`mt-3 h-10 rounded-md ${
									index === 1 || index === 3
										? "bg-primary/90"
										: "bg-[color-mix(in_srgb,var(--color-chart-3)_42%,var(--color-card))]"
								}`}
							/>
						</div>
					))}
				</div>
			</div>
		);
	}

	if (type === "publish") {
		return (
			<div
				data-workflow-preview="publish"
				className="relative h-44 overflow-hidden rounded-xl border border-border bg-muted/45 p-4"
			>
				<div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-card p-3">
					<div>
						<p className="text-sm font-semibold">Ready to publish</p>
						<p className="mt-1 text-xs text-muted-foreground">
							Threads + Instagram
						</p>
					</div>
					<Badge tone="secondary">Safe</Badge>
				</div>
				<div className="mt-3 grid gap-1.5">
					{["Token active", "Media attached", "Smart link checked"].map(
						(item) => (
							<div
								key={item}
								className="flex items-center gap-2 text-xs font-medium text-muted-foreground"
							>
								<Check
									aria-hidden="true"
									className="size-3.5 shrink-0 text-primary"
								/>
								<span>{item}</span>
							</div>
						),
					)}
				</div>
			</div>
		);
	}

	if (type === "inbox") {
		return (
			<div
				data-workflow-preview="inbox"
				className="relative h-44 overflow-hidden rounded-xl border border-border bg-muted/45 p-4"
			>
				<div className="grid gap-2">
					{[
						["High priority", "12"],
						["Assigned", "18"],
						["Draft replies", "9"],
					].map(([label, value]) => (
						<div
							key={label}
							className="flex items-center justify-between rounded-lg border border-border bg-card px-3 py-2"
						>
							<span className="text-sm font-medium">{label}</span>
							<span className="rounded-full bg-primary px-2 py-0.5 text-xs font-semibold text-primary-foreground">
								{value}
							</span>
						</div>
					))}
				</div>
			</div>
		);
	}

	return (
		<div
			data-workflow-preview="analytics"
			className="relative h-44 overflow-hidden rounded-xl border border-border bg-muted/45 p-4"
		>
			<div className="relative z-10 flex items-start justify-between gap-3">
				<div>
					<p className="text-sm font-semibold">Content signal</p>
					<p className="mt-1 text-xs text-muted-foreground">
						Next plan from live posts
					</p>
				</div>
				<Badge tone="secondary">+22%</Badge>
			</div>
			<svg
				aria-hidden="true"
				viewBox="0 0 420 120"
				className="absolute inset-x-4 top-10 h-24 w-[calc(100%-2rem)] text-primary"
				preserveAspectRatio="none"
			>
				<path
					d="M0 96 H420 M0 66 H420 M0 36 H420"
					fill="none"
					stroke="currentColor"
					strokeOpacity="0.08"
					strokeWidth="1"
				/>
				<path
					d="M0 91 C38 82 62 86 96 70 C132 52 155 63 190 43 C230 20 260 36 296 27 C337 18 365 31 420 12"
					fill="none"
					stroke="currentColor"
					strokeLinecap="round"
					strokeWidth="4"
				/>
				<path
					d="M0 91 C38 82 62 86 96 70 C132 52 155 63 190 43 C230 20 260 36 296 27 C337 18 365 31 420 12 L420 120 L0 120 Z"
					fill="currentColor"
					opacity="0.12"
				/>
			</svg>
			<div className="absolute inset-x-4 bottom-4 flex h-14 items-end gap-2">
				{[26, 44, 38, 58, 49, 74, 63, 86].map((height, index) => (
					<div
						key={index}
						className="flex flex-1 flex-col justify-end rounded-full bg-background"
					>
						<div
							className="rounded-full bg-[color-mix(in_srgb,var(--color-primary)_78%,var(--color-card))]"
							style={{ height: `${height}%` }}
						/>
					</div>
				))}
			</div>
		</div>
	);
}

function WorkflowCard({ step }: { step: (typeof workflowSteps)[number] }) {
	const Icon = step.icon;
	return (
		<div
			className={`group/workflow flex min-h-[21rem] min-w-0 flex-col overflow-hidden rounded-2xl border border-border bg-card p-5 text-card-foreground shadow-sm transition duration-200 hover:-translate-y-0.5 hover:shadow-md ${step.className}`}
		>
			<WorkflowPreview type={step.preview} />
			<div className="mt-5 flex min-w-0 items-start gap-4">
				<span className="grid size-11 shrink-0 place-items-center rounded-xl bg-primary text-primary-foreground shadow-sm">
					<Icon aria-hidden="true" />
				</span>
				<div className="min-w-0">
					<h3 className="text-xl font-semibold tracking-normal text-foreground">
						{step.title}
					</h3>
					<p className="mt-2 text-sm leading-6 text-muted-foreground">
						{step.description}
					</p>
				</div>
			</div>
		</div>
	);
}

function AnalyticsMetricsPanel() {
	return (
		<div
			data-landing-stat-card
			className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm"
		>
			<div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3 sm:px-5">
				<div>
					<p className="text-sm font-semibold">Live operating metrics</p>
					<p className="mt-1 text-xs text-muted-foreground">
						Reach, engagement, and inbox load in one read.
					</p>
				</div>
				<Badge tone="secondary">Updated now</Badge>
			</div>
			<div className="divide-y divide-border">
				{analyticsCards.map((item) => {
					const Icon = item.icon;
					const max = Math.max(...item.series);
					const min = Math.min(...item.series);
					const range = Math.max(max - min, 1);
					const points = item.series
						.map((value, index) => {
							const x = (index / (item.series.length - 1)) * 180;
							const y = 56 - ((value - min) / range) * 42;
							return `${x.toFixed(1)},${y.toFixed(1)}`;
						})
						.join(" ");

					return (
						<div
							key={item.label}
							className="grid gap-4 px-4 py-4 sm:grid-cols-[1fr_12rem] sm:items-center sm:px-5"
						>
							<div className="flex min-w-0 items-center gap-3">
								<span className="grid size-10 shrink-0 place-items-center rounded-xl border border-border bg-background text-primary shadow-sm">
									<Icon aria-hidden="true" className="size-5" />
								</span>
								<div className="min-w-0">
									<p className="text-sm font-medium text-muted-foreground">
										{item.label}
									</p>
									<div className="mt-1 flex flex-wrap items-end gap-x-3 gap-y-1">
										<p className="text-3xl font-semibold leading-none tracking-normal">
											{item.value}
										</p>
										<span className="rounded-full bg-[color-mix(in_srgb,var(--color-success)_14%,var(--color-card))] px-2 py-1 text-xs font-semibold text-[color-mix(in_srgb,var(--color-success)_72%,var(--color-foreground))]">
											{item.change}
										</span>
									</div>
									<p className="mt-1 text-xs text-muted-foreground">
										{item.detail}
									</p>
								</div>
							</div>
							<svg
								aria-hidden="true"
								viewBox="0 0 180 64"
								className="h-16 w-full text-primary"
								preserveAspectRatio="none"
							>
								<path
									d="M0 56 H180 M0 34 H180 M0 12 H180"
									fill="none"
									stroke="currentColor"
									strokeOpacity="0.08"
									strokeWidth="1"
								/>
								<polyline
									fill="none"
									points={points}
									stroke="currentColor"
									strokeLinecap="round"
									strokeLinejoin="round"
									strokeWidth="4"
								/>
							</svg>
						</div>
					);
				})}
			</div>
		</div>
	);
}

function PostPerformanceChart() {
	const points = [
		[0, 118],
		[54, 100],
		[108, 106],
		[162, 72],
		[216, 86],
		[270, 50],
		[324, 64],
		[390, 30],
		[460, 42],
		[520, 20],
	];
	const linePath = points
		.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x} ${y}`)
		.join(" ");
	const areaPath = `${linePath} L520 150 L0 150 Z`;

	return (
		<div
			data-post-performance-chart
			className="relative h-48 overflow-hidden rounded-xl border border-border bg-[linear-gradient(180deg,var(--color-card),color-mix(in_srgb,var(--color-primary)_5%,var(--color-card)))] p-4"
		>
			<svg
				aria-hidden="true"
				viewBox="0 0 520 150"
				className="absolute inset-4 h-[calc(100%-2rem)] w-[calc(100%-2rem)] text-primary"
				preserveAspectRatio="none"
			>
				<path
					d="M0 122 H520 M0 86 H520 M0 50 H520"
					fill="none"
					stroke="currentColor"
					strokeOpacity="0.1"
					strokeWidth="1"
				/>
				<path d={areaPath} fill="currentColor" opacity="0.12" />
				<path
					d={linePath}
					fill="none"
					stroke="currentColor"
					strokeLinecap="round"
					strokeLinejoin="round"
					strokeWidth="4"
				/>
				{points.slice(1, -1).map(([x, y]) => (
					<circle
						key={`${x}-${y}`}
						cx={x}
						cy={y}
						fill="var(--color-card)"
						r="5"
						stroke="currentColor"
						strokeWidth="3"
					/>
				))}
			</svg>
			<div className="absolute inset-x-4 bottom-4 grid grid-cols-3 gap-2">
				{[
					["Reach", "84K"],
					["Replies", "24"],
					["Ready", "9:00 AM"],
				].map(([label, value]) => (
					<div
						key={label}
						className="rounded-lg border border-border bg-background/90 px-3 py-2 shadow-sm"
					>
						<p className="text-[11px] font-medium text-muted-foreground">
							{label}
						</p>
						<p className="mt-1 text-sm font-semibold">{value}</p>
					</div>
				))}
			</div>
		</div>
	);
}

function AnalyticsPulsePanel() {
	return (
		<div className="relative overflow-hidden rounded-2xl border border-border bg-[color-mix(in_srgb,var(--color-foreground)_96%,black)] p-4 text-primary-foreground shadow-sm sm:p-5">
			<div
				aria-hidden="true"
				className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_78%_10%,color-mix(in_srgb,var(--color-primary)_28%,transparent),transparent_32%)]"
			/>
			<svg
				aria-hidden="true"
				viewBox="0 0 520 150"
				className="pointer-events-none absolute inset-x-4 top-20 h-28 w-[calc(100%-2rem)] text-primary opacity-90"
				preserveAspectRatio="none"
			>
				<defs>
					<linearGradient
						id="landing-analytics-area"
						x1="0"
						x2="0"
						y1="0"
						y2="1"
					>
						<stop stopColor="currentColor" stopOpacity="0.35" />
						<stop offset="1" stopColor="currentColor" stopOpacity="0" />
					</linearGradient>
				</defs>
				<path
					d="M0 112 C45 92 70 102 110 78 C155 50 185 72 228 45 C270 18 305 42 342 31 C386 18 420 39 456 22 C486 8 505 16 520 10 L520 150 L0 150 Z"
					fill="url(#landing-analytics-area)"
				/>
				<path
					d="M0 112 C45 92 70 102 110 78 C155 50 185 72 228 45 C270 18 305 42 342 31 C386 18 420 39 456 22 C486 8 505 16 520 10"
					fill="none"
					stroke="currentColor"
					strokeLinecap="round"
					strokeWidth="4"
				/>
				<path
					d="M0 124 H520 M0 84 H520 M0 44 H520"
					fill="none"
					stroke="white"
					strokeOpacity="0.08"
					strokeWidth="1"
				/>
			</svg>
			<div className="relative z-10 flex items-start justify-between gap-4">
				<div>
					<p className="text-sm font-medium text-white/62">Audience pulse</p>
					<p className="mt-2 text-4xl font-semibold tracking-normal">+18.2%</p>
				</div>
				<span className="grid size-11 place-items-center rounded-xl bg-primary text-primary-foreground">
					<Gauge aria-hidden="true" />
				</span>
			</div>
			<div className="relative z-10 mt-24 flex h-16 items-end gap-2 sm:mt-20">
				{[32, 42, 38, 61, 54, 74, 68, 82, 76, 88, 84, 92].map(
					(height, index) => (
						<div key={index} className="flex flex-1 flex-col justify-end">
							<div
								className="rounded-t-md bg-[linear-gradient(180deg,color-mix(in_srgb,var(--color-primary)_95%,white),color-mix(in_srgb,var(--color-primary)_42%,transparent))]"
								style={{ height: `${height}%` }}
							/>
						</div>
					),
				)}
			</div>
			<div className="relative z-10 mt-5 grid gap-2">
				{analyticsBreakdown.map((item) => (
					<div
						key={item.label}
						className="grid grid-cols-[6rem_1fr_3rem] items-center gap-3 text-xs"
					>
						<span className="text-white/64">{item.label}</span>
						<div className="h-2 overflow-hidden rounded-full bg-white/12">
							<div
								className="h-full rounded-full"
								style={{ width: item.value, backgroundColor: item.color }}
							/>
						</div>
						<span className="text-right font-semibold text-white">
							{item.value}
						</span>
					</div>
				))}
			</div>
		</div>
	);
}

/**
 * Public marketing page at `/`.
 *
 * Logged-in users still redirect into the product. The page intentionally uses
 * landing-owned visual primitives instead of NovaScreen so public marketing
 * can feel like Stripe/Raycast without changing the internal app shell.
 */
export function Landing() {
	const navigate = useNavigate();
	const [checkedSession, setCheckedSession] = useState(false);

	useEffect(() => {
		let cancelled = false;
		supabaseAuth
			.getSession()
			.then((session) => {
				if (cancelled) return;
				if (session) {
					navigate("/dashboard", { replace: true });
				} else {
					setCheckedSession(true);
				}
			})
			.catch(() => {
				if (!cancelled) setCheckedSession(true);
			});
		return () => {
			cancelled = true;
		};
	}, [navigate]);

	if (!checkedSession) return null;

	return (
		<MarketingShell>
			<header className="sticky top-0 z-40 border-b border-border/80 bg-[color-mix(in_srgb,var(--color-background)_86%,transparent)] backdrop-blur-xl">
				<MarketingContainer className="flex h-16 items-center justify-between gap-5">
					<Link
						to="/"
						className="flex items-center gap-3 font-semibold tracking-tight"
					>
						<span className="grid size-8 place-items-center rounded-lg border border-[color-mix(in_srgb,var(--color-primary)_30%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-primary)_8%,var(--color-card))] text-primary">
							<span className="size-3.5 rotate-45 rounded-[3px] border-2 border-current" />
						</span>
						<span className="text-lg">Juno33</span>
					</Link>
					<nav className="hidden items-center gap-8 text-sm font-medium text-muted-foreground lg:flex">
						<a
							href="#product"
							className="inline-flex items-center gap-1 transition-colors hover:text-foreground"
						>
							Product
							<ChevronDown aria-hidden="true" />
						</a>
						<a
							href="#workflows"
							className="transition-colors hover:text-foreground"
						>
							Workflows
						</a>
						<a
							href="#analytics"
							className="transition-colors hover:text-foreground"
						>
							Analytics
						</a>
						<a
							href="#pricing"
							className="transition-colors hover:text-foreground"
						>
							Pricing
						</a>
					</nav>
					<div className="flex items-center gap-2">
						<Button variant="outline" size="sm" asChild>
							<Link to="/login">Sign in</Link>
						</Button>
						<Button size="sm" asChild>
							<Link to="/signup">
								Start free
								<ArrowRight data-icon="inline-end" aria-hidden="true" />
							</Link>
						</Button>
					</div>
				</MarketingContainer>
			</header>

			<main>
				<section className="relative overflow-hidden border-b border-border/80">
					<HeroBeams />
					<Suspense fallback={null}>
						<div
							className="pointer-events-none absolute inset-0 z-0"
							aria-hidden="true"
						>
							<HeroSparkles
							className="absolute inset-0"
							density={34}
							opacity={0.45}
						/>
						</div>
					</Suspense>
					<MarketingContainer className="relative z-10 grid min-h-[calc(100svh-5rem)] min-w-0 gap-8 py-10 sm:py-14 lg:grid-cols-[minmax(0,0.68fr)_minmax(0,1fr)] lg:items-center lg:py-5">
						<div className="relative z-10 flex min-w-0 max-w-full flex-col gap-5 lg:max-w-2xl">
							<div className="flex min-w-0 max-w-full flex-col gap-4">
								<h1 className="max-w-[13ch] text-5xl font-semibold leading-none tracking-normal text-foreground sm:text-6xl lg:text-[3.65rem] xl:text-[3.85rem]">
									Run every social account from one command center.
								</h1>
								<p className="max-w-full text-lg leading-8 text-muted-foreground sm:max-w-xl">
									Plan content, publish across Threads and Instagram, triage
									your inbox, and track performance in one fast, intelligent
									workspace for teams.
								</p>
							</div>

							<div className="flex min-w-0 max-w-full flex-col gap-3 sm:w-auto sm:flex-row">
								<Button
									size="lg"
									className="h-12 w-full px-7 text-base sm:w-auto"
									asChild
								>
									<Link to="/signup">
										Start free
										<ArrowRight data-icon="inline-end" aria-hidden="true" />
									</Link>
								</Button>
								<Button
									size="lg"
									variant="outline"
									className="h-12 w-full px-7 text-base sm:w-auto"
									asChild
								>
									<a href="#product">
										<PlayCircle data-icon="inline-start" aria-hidden="true" />
										Watch demo
									</a>
								</Button>
							</div>

							<div className="flex min-w-0 max-w-full flex-col gap-3">
								<p className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">
									Built for the stack social teams already use
								</p>
								<div className="flex min-w-0 max-w-xl flex-wrap gap-2">
									{integrationLogos.slice(0, 4).map((logo) => (
										<div
											key={logo.name}
											className="flex min-w-max items-center gap-2 rounded-xl border border-border bg-card px-4 py-2 text-sm font-semibold text-foreground shadow-sm"
										>
											<BrandLogo name={logo.name} size="sm" />
											<span>{logo.label}</span>
										</div>
									))}
									<div className="flex min-w-max items-center rounded-xl border border-border bg-muted/55 px-4 py-2 text-sm font-semibold text-muted-foreground">
										+4 more
									</div>
								</div>
							</div>

							<dl className="grid max-w-xl grid-cols-3 gap-3 border-t border-border/70 pt-5">
								{heroStats.map((stat) => (
									<div key={stat.label} className="min-w-0">
										<dt className="sr-only">{stat.label}</dt>
										<dd className="text-3xl font-semibold tracking-normal text-foreground">
											<AnimatedNumber
												value={stat.value}
												format={(v) => `${Math.round(v)}${stat.suffix}`}
											/>
										</dd>
										<p className="mt-1 text-xs leading-5 text-muted-foreground">
											{stat.label}
										</p>
									</div>
								))}
							</dl>
						</div>

						<div className="relative z-10 min-w-0 lg:origin-center lg:scale-[0.72] 2xl:scale-100">
							<ContainerScroll
								compact
								cardClassName="max-w-[920px] border-0 bg-transparent p-0 shadow-none"
								contentClassName="overflow-visible rounded-none bg-transparent"
							>
								<LandingProductMockup />
							</ContainerScroll>
						</div>
					</MarketingContainer>
				</section>

				<section
					id="product"
					className="relative overflow-hidden border-b border-border/80 bg-background py-14 sm:py-20"
				>
					<MarketingContainer className="relative">
						<div
							id="workflows"
							className="mx-auto mb-10 flex max-w-3xl scroll-mt-24 flex-col gap-4 text-center"
						>
							<h2 className="text-3xl font-semibold tracking-normal sm:text-5xl">
								From plan to performance without platform hopping.
							</h2>
							<p className="text-base leading-7 text-muted-foreground sm:text-lg">
								Juno33 keeps each daily social workflow in one chain so teams
								know what to publish, who should respond, and which content
								deserves another push.
							</p>
						</div>
						<BentoGrid className="md:auto-rows-auto">
							{workflowSteps.map((step) => (
								<WorkflowCard key={step.title} step={step} />
							))}
						</BentoGrid>
					</MarketingContainer>
				</section>

				<section
					id="analytics"
					className="border-b border-border/80 bg-background py-16 sm:py-24"
				>
					<MarketingContainer className="grid gap-8 lg:grid-cols-[minmax(0,0.9fr)_minmax(420px,0.55fr)] lg:items-start">
						<SpotlightCard className="overflow-hidden p-0">
							<div className="border-b border-border p-6 sm:p-8">
								<h2 className="text-3xl font-semibold tracking-normal sm:text-5xl">
									Know what worked before the next post goes out.
								</h2>
								<p className="mt-4 max-w-2xl text-base leading-7 text-muted-foreground">
									Dashboard views stay operational. Analytics goes deeper with
									post tables, audience readiness, account comparisons, and
									clear unavailable states.
								</p>
							</div>
							<div className="grid gap-4 p-5 sm:grid-cols-2 sm:p-6 lg:p-8">
								<div className="sm:col-span-2">
									<AnalyticsPulsePanel />
								</div>
								<div className="sm:col-span-2">
									<AnalyticsMetricsPanel />
								</div>
							</div>
							<div className="border-t border-border bg-muted/35 p-5 sm:p-6 lg:p-8">
								<div className="rounded-2xl border border-border bg-card p-4 shadow-sm sm:p-5">
									<div className="mb-5 flex flex-wrap items-center justify-between gap-3">
										<div>
											<p className="text-sm font-semibold">
												Post performance mix
											</p>
											<p className="mt-1 text-xs text-muted-foreground">
												Reach, replies, and readiness in the same operating
												view.
											</p>
										</div>
										<Badge tone="outline">Live window</Badge>
									</div>
									<div className="grid gap-3 sm:grid-cols-[1fr_0.72fr]">
										<PostPerformanceChart />
										<div className="grid gap-2">
											{[
												["Best post", "Behind-the-scenes reel", "84K views"],
												["Needs action", "Replies waiting", "24 open"],
												["Next slot", "Tomorrow 9:00 AM", "Ready"],
											].map(([label, title, value]) => (
												<div
													key={label}
													className="rounded-xl border border-border bg-muted/45 p-3"
												>
													<p className="text-xs font-medium text-muted-foreground">
														{label}
													</p>
													<p className="mt-1 text-sm font-semibold">{title}</p>
													<p className="mt-2 text-xs text-primary">{value}</p>
												</div>
											))}
										</div>
									</div>
								</div>
							</div>
						</SpotlightCard>

						<SpotlightCard className="flex flex-col justify-between p-7 lg:sticky lg:top-24">
							<div className="flex flex-col gap-7">
								<div className="flex items-start justify-between gap-4">
									<span className="grid size-12 place-items-center rounded-xl bg-primary text-primary-foreground shadow-sm">
										<ShieldCheck aria-hidden="true" />
									</span>
									<Badge tone="outline">Operational proof</Badge>
								</div>
								<div>
									<h3 className="text-3xl font-semibold tracking-normal">
										Designed for real publish operations, not vanity proof.
									</h3>
									<p className="mt-4 text-sm leading-6 text-muted-foreground">
										The landing page should show what the product controls:
										readiness, account scope, inbox ownership, and analytics
										context. No invented customer quote needed.
									</p>
								</div>
								<div className="grid gap-3">
									{operationalProof.map((item) => (
										<div
											key={item}
											className="flex items-start gap-3 rounded-xl border border-border bg-muted/50 p-3 text-sm font-medium"
										>
											<Check
												aria-hidden="true"
												className="mt-0.5 shrink-0 text-primary"
											/>
											<span>{item}</span>
										</div>
									))}
								</div>
							</div>
							<div className="mt-10 grid gap-3 border-t border-border pt-6 sm:grid-cols-2">
								<div>
									<p className="text-sm font-medium text-muted-foreground">
										Platform scope
									</p>
									<div className="mt-2 flex items-center gap-2 text-sm font-semibold">
										<BrandLogo name="threads" size="sm" />
										<BrandLogo name="instagram" size="sm" />
										<span>Threads + Instagram</span>
									</div>
								</div>
								<div>
									<p className="text-sm font-medium text-muted-foreground">
										Team model
									</p>
									<div className="mt-2 flex items-center gap-2 text-sm font-semibold">
										<Users aria-hidden="true" className="text-primary" />
										<span>Account groups</span>
									</div>
								</div>
							</div>
						</SpotlightCard>
					</MarketingContainer>
				</section>

				<section className="relative overflow-hidden border-b border-border/80 bg-[var(--color-surface-frame)] py-16 sm:py-24">
					<MarketingContainer className="flex flex-col gap-12">
						<div className="flex flex-col gap-3 text-center">
							<p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
								Trusted by operators running social at scale
							</p>
							<LogoMarquee>
								{integrationLogos.map((logo) => (
									<div
										key={`proof-${logo.name}`}
										className="mx-2 flex min-w-max items-center gap-2 rounded-xl border border-border bg-card px-4 py-2 text-sm font-semibold text-foreground shadow-sm"
									>
										<BrandLogo name={logo.name} size="sm" />
										<span>{logo.label}</span>
									</div>
								))}
							</LogoMarquee>
						</div>

						<InfiniteMovingCards items={testimonials} speed="slow" />

						<dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
							{proofStats.map((stat) => (
								<div
									key={stat.label}
									className="rounded-2xl border border-border bg-card p-5 text-center shadow-sm"
								>
									<dt className="sr-only">{stat.label}</dt>
									<dd className="text-4xl font-semibold tracking-normal text-foreground">
										<AnimatedNumber
											value={stat.value}
											format={(v) =>
												`${
													"decimals" in stat && stat.decimals
														? v.toFixed(stat.decimals)
														: Math.round(v)
												}${stat.suffix}`
											}
										/>
									</dd>
									<p className="mt-2 text-xs leading-5 text-muted-foreground">
										{stat.label}
									</p>
								</div>
							))}
						</dl>
					</MarketingContainer>
				</section>

				<section
					id="pricing"
					className="border-b border-border/80 py-16 sm:py-24"
				>
					<MarketingContainer className="grid gap-8 lg:grid-cols-[minmax(0,0.75fr)_minmax(420px,0.55fr)] lg:items-start">
						<div className="flex max-w-3xl flex-col gap-5">
							<h2 className="text-3xl font-semibold tracking-normal sm:text-5xl">
								Start with the operating system your social team actually needs.
							</h2>
							<p className="text-base leading-7 text-muted-foreground sm:text-lg">
								Bring planning, publishing, inbox, and analytics into one place
								before adding more accounts, automations, and reporting
								workflows.
							</p>
							<div className="grid gap-3 sm:grid-cols-3">
								{[
									"No card to explore",
									"Team-ready workspace",
									"Upgrade when the fleet grows",
								].map((item) => (
									<div
										key={item}
										className="flex items-center gap-2 text-sm font-medium"
									>
										<Check aria-hidden="true" className="text-primary" />
										<span>{item}</span>
									</div>
								))}
							</div>
						</div>
						<SpotlightCard className="p-6 sm:p-8">
							<div className="flex items-start justify-between gap-4">
								<div>
									<p className="text-sm font-medium text-muted-foreground">
										Team workspace
									</p>
									<p className="mt-2 text-5xl font-semibold tracking-normal">
										Start free
									</p>
								</div>
								<Badge tone="oxblood">Popular</Badge>
							</div>
							<div className="mt-8 flex flex-col gap-3">
								<Button size="lg" asChild>
									<Link to="/signup">
										Create workspace
										<ArrowRight data-icon="inline-end" aria-hidden="true" />
									</Link>
								</Button>
								<Button size="lg" variant="outline" asChild>
									<Link to="/login">Sign in</Link>
								</Button>
							</div>
							<form action="/signup" className="mt-6 flex flex-col gap-3">
								<Input
									type="email"
									name="email"
									placeholder="operator@company.com"
									autoComplete="email"
									leadingIcon={<Sparkles aria-hidden="true" />}
								/>
								<p className="text-sm leading-6 text-muted-foreground">
									We will send the product walkthrough and workspace setup link.
								</p>
							</form>
						</SpotlightCard>
					</MarketingContainer>
				</section>

				<section id="faq" className="bg-background py-16 sm:py-24">
					<MarketingContainer className="grid gap-8 lg:grid-cols-[minmax(260px,0.45fr)_minmax(0,0.75fr)]">
						<div>
							<h2 className="text-3xl font-semibold tracking-normal">
								Questions teams ask before switching.
							</h2>
							<p className="mt-4 text-base leading-7 text-muted-foreground">
								The short version: Juno33 is built for teams managing many
								social accounts, not solo posting from a phone.
							</p>
						</div>
						<Accordion
							type="single"
							collapsible
							className="rounded-2xl border border-border bg-card px-5"
						>
							{faqs.map((faq) => (
								<AccordionItem key={faq.question} value={faq.question}>
									<AccordionTrigger className="text-left text-base font-semibold">
										{faq.question}
									</AccordionTrigger>
									<AccordionContent className="text-sm leading-6 text-muted-foreground">
										{faq.answer}
									</AccordionContent>
								</AccordionItem>
							))}
						</Accordion>
					</MarketingContainer>
				</section>
			</main>

			<footer className="border-t border-border bg-[var(--color-surface-frame)]">
				<MarketingContainer className="py-14">
					<div className="grid gap-10 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
						<div className="flex max-w-sm flex-col gap-4">
							<div className="flex items-center gap-3 font-semibold">
								<span className="grid size-8 place-items-center rounded-lg border border-[color-mix(in_srgb,var(--color-primary)_30%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-primary)_8%,var(--color-card))] text-primary">
									<span className="size-3.5 rotate-45 rounded-[3px] border-2 border-current" />
								</span>
								<span className="text-lg">Juno33</span>
							</div>
							<p className="text-sm leading-6 text-muted-foreground">
								The operator command center for social teams running Threads and
								Instagram at scale.
							</p>
							<div className="flex flex-wrap gap-2">
								<Button size="sm" asChild>
									<Link to="/signup">
										Start free
										<ArrowRight data-icon="inline-end" aria-hidden="true" />
									</Link>
								</Button>
								<Button size="sm" variant="outline" asChild>
									<Link to="/login">Sign in</Link>
								</Button>
							</div>
						</div>
						<div className="grid grid-cols-2 gap-8 sm:grid-cols-3">
							<div className="flex flex-col gap-3">
								<p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
									Product
								</p>
								<a href="#product" className="text-sm text-muted-foreground hover:text-foreground">
									Workflows
								</a>
								<a href="#analytics" className="text-sm text-muted-foreground hover:text-foreground">
									Analytics
								</a>
								<a href="#pricing" className="text-sm text-muted-foreground hover:text-foreground">
									Pricing
								</a>
								<a href="#faq" className="text-sm text-muted-foreground hover:text-foreground">
									FAQ
								</a>
							</div>
							<div className="flex flex-col gap-3">
								<p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
									Account
								</p>
								<Link to="/login" className="text-sm text-muted-foreground hover:text-foreground">
									Sign in
								</Link>
								<Link to="/signup" className="text-sm text-muted-foreground hover:text-foreground">
									Start free
								</Link>
							</div>
							<div className="flex flex-col gap-3">
								<p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
									Legal
								</p>
								<Link to="/privacy" className="text-sm text-muted-foreground hover:text-foreground">
									Privacy
								</Link>
								<Link to="/terms" className="text-sm text-muted-foreground hover:text-foreground">
									Terms
								</Link>
							</div>
						</div>
					</div>
					<div className="mt-10 flex flex-col gap-3 border-t border-border pt-6 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
						<span>© {new Date().getFullYear()} Juno33. All rights reserved.</span>
						<span className="flex items-center gap-2">
							<BrandLogo name="threads" size="sm" />
							<BrandLogo name="instagram" size="sm" />
							Built for Threads + Instagram
						</span>
					</div>
				</MarketingContainer>
			</footer>
		</MarketingShell>
	);
}
