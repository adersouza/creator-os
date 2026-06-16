import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
	ArrowRight,
	BarChart3,
	CalendarDays,
	Check,
	ChevronDown,
	Inbox,
	Library,
	PlayCircle,
	ShieldCheck,
	Sparkles,
	Users,
	Zap,
} from "lucide-react";
import {
	Accordion,
	AccordionContent,
	AccordionItem,
	AccordionTrigger,
} from "@/components/ui/Accordion";
import { Badge } from "@/components/ui/Badge";
import { BrandLogo, type BrandLogoName } from "@/components/ui/BrandLogo";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import {
	HeroBeams,
	LogoMarquee,
	MarketingContainer,
	MarketingShell,
	SpotlightCard,
	WorkflowBeam,
} from "@/components/landing/LandingEffects";
import { LandingProductMockup } from "@/components/landing/LandingProductMockup";
import { cn } from "@/lib/utils";
import { supabaseAuth } from "@/services/supabase";

const proofLogos: Array<{ name: BrandLogoName; label: string }> = [
	{ name: "instagram", label: "Instagram" },
	{ name: "threads", label: "Threads" },
	{ name: "stripe", label: "Stripe" },
	{ name: "supabase", label: "Supabase" },
	{ name: "vercel", label: "Vercel" },
	{ name: "posthog", label: "PostHog" },
	{ name: "openai", label: "OpenAI" },
	{ name: "anthropic", label: "Anthropic" },
];

const featureCards = [
	{
		title: "Schedule smarter",
		description:
			"Plan and auto-publish content across Threads and Instagram with an intuitive calendar.",
		icon: CalendarDays,
		className: "lg:col-span-5",
	},
	{
		title: "Content performance",
		description:
			"Track reach, engagement, saves, replies, and what each post actually changed.",
		icon: BarChart3,
		className: "lg:col-span-4",
	},
	{
		title: "Unified inbox",
		description:
			"Triage comments, DMs, assignments, and AI reply drafts from one place.",
		icon: Inbox,
		className: "lg:col-span-3",
	},
	{
		title: "AI drafts that sound like you",
		description:
			"Generate on-brand captions and follow-ups with workspace context and approval controls.",
		icon: Sparkles,
		className: "lg:col-span-4",
	},
	{
		title: "Account health",
		description:
			"Monitor connection status, publishing readiness, and posting gaps before they become problems.",
		icon: ShieldCheck,
		className: "lg:col-span-4",
	},
	{
		title: "Team-first analytics",
		description:
			"Share reports, compare accounts, and align your team with the metrics that matter.",
		icon: Users,
		className: "lg:col-span-4",
	},
];

const workflowSteps = [
	{
		title: "Plan",
		description: "Build the week across every account and spot gaps before they hit.",
		icon: CalendarDays,
	},
	{
		title: "Publish",
		description: "Queue posts, check readiness, and keep approvals moving.",
		icon: Zap,
	},
	{
		title: "Reply",
		description: "Route the inbox by owner, priority, account, and platform.",
		icon: Inbox,
	},
	{
		title: "Learn",
		description: "Turn the top posts and weak signals into tomorrow's plan.",
		icon: BarChart3,
	},
];

const analyticsCards = [
	{ label: "Views", value: "512K", detail: "+8.7% vs prior window" },
	{ label: "People reached", value: "142K", detail: "Across active account scope" },
	{ label: "Engagement rate", value: "3.6%", detail: "Weighted by reach" },
	{ label: "Waiting for reply", value: "24", detail: "Prioritized conversations" },
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
					<Link to="/" className="flex items-center gap-3 font-semibold tracking-tight">
						<span className="grid size-8 place-items-center rounded-lg border border-[color-mix(in_srgb,var(--color-primary)_30%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-primary)_8%,var(--color-card))] text-primary">
							<span className="size-3.5 rotate-45 rounded-[3px] border-2 border-current" />
						</span>
						<span className="text-lg">Juno33</span>
					</Link>
					<nav className="hidden items-center gap-8 text-sm font-medium text-muted-foreground lg:flex">
						<a href="#product" className="inline-flex items-center gap-1 transition-colors hover:text-foreground">
							Product
							<ChevronDown aria-hidden="true" />
						</a>
						<a href="#workflows" className="transition-colors hover:text-foreground">
							Workflows
						</a>
						<a href="#analytics" className="transition-colors hover:text-foreground">
							Analytics
						</a>
						<a href="#pricing" className="transition-colors hover:text-foreground">
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
					<MarketingContainer className="relative grid min-h-[calc(100svh-4rem)] min-w-0 gap-10 py-14 sm:py-20 lg:grid-cols-[minmax(0,0.76fr)_minmax(620px,1.14fr)] lg:items-center lg:py-8">
						<div className="relative z-10 flex min-w-0 max-w-full flex-col gap-8 lg:max-w-2xl">
							<div className="flex min-w-0 max-w-full flex-col gap-6">
								<h1 className="max-w-[11ch] text-5xl font-semibold leading-[0.96] tracking-[-0.06em] text-foreground sm:text-6xl lg:text-7xl">
									Run every social account from one command center.
								</h1>
								<p className="max-w-full text-lg leading-8 text-muted-foreground sm:max-w-xl">
									Plan content, publish across Threads and Instagram, triage your inbox, and track performance in one fast, intelligent workspace for teams.
								</p>
							</div>

							<div className="flex min-w-0 max-w-full flex-col gap-3 sm:w-auto sm:flex-row">
								<Button size="lg" className="h-12 w-full px-7 text-base sm:w-auto" asChild>
									<Link to="/signup">
										Start free
										<ArrowRight data-icon="inline-end" aria-hidden="true" />
									</Link>
								</Button>
								<Button size="lg" variant="outline" className="h-12 w-full px-7 text-base sm:w-auto" asChild>
									<a href="#product">
										<PlayCircle data-icon="inline-start" aria-hidden="true" />
										Watch demo
									</a>
								</Button>
							</div>

							<div className="flex min-w-0 max-w-full flex-col gap-3">
								<p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
									Trusted by modern social teams
								</p>
								<div className="min-w-0 max-w-full overflow-hidden sm:max-w-xl">
									<LogoMarquee>
										{proofLogos.map((logo) => (
											<div
												key={logo.name}
												className="flex min-w-max items-center gap-2 rounded-xl border border-border bg-card px-4 py-2 text-sm font-semibold text-foreground shadow-sm"
											>
												<BrandLogo name={logo.name} size="sm" />
												<span>{logo.label}</span>
											</div>
										))}
									</LogoMarquee>
								</div>
							</div>
						</div>

						<div className="relative z-10 min-w-0 lg:-mr-10">
							<LandingProductMockup />
						</div>
					</MarketingContainer>
				</section>

				<section id="product" className="border-b border-border/80 bg-background py-8 sm:py-12">
					<MarketingContainer className="grid gap-5 lg:grid-cols-12">
						{featureCards.map((feature) => {
							const Icon = feature.icon;
							return (
								<SpotlightCard
									key={feature.title}
									className={cn("min-h-[12rem] p-6 transition-transform duration-200 hover:-translate-y-0.5", feature.className)}
								>
									<div className="relative z-10 flex h-full flex-col justify-between gap-8">
										<div className="flex items-start justify-between gap-4">
											<span className="grid size-11 place-items-center rounded-xl bg-primary text-primary-foreground shadow-sm">
												<Icon aria-hidden="true" />
											</span>
											<ArrowRight aria-hidden="true" className="text-muted-foreground" />
										</div>
										<div className="flex flex-col gap-2">
											<h2 className="text-xl font-semibold tracking-tight">{feature.title}</h2>
											<p className="max-w-sm text-sm leading-6 text-muted-foreground">{feature.description}</p>
										</div>
									</div>
								</SpotlightCard>
							);
						})}
					</MarketingContainer>
				</section>

				<section id="workflows" className="relative overflow-hidden border-b border-border/80 py-16 sm:py-24">
					<MarketingContainer className="relative">
						<WorkflowBeam />
						<div className="mx-auto mb-12 flex max-w-3xl flex-col gap-4 text-center">
							<h2 className="text-3xl font-semibold tracking-[-0.04em] sm:text-5xl">
								From plan to performance without platform hopping.
							</h2>
							<p className="text-base leading-7 text-muted-foreground sm:text-lg">
								Juno33 keeps each daily social workflow in one chain so teams know what to publish, who should respond, and which content deserves another push.
							</p>
						</div>
						<div className="relative grid gap-4 lg:grid-cols-4">
							{workflowSteps.map((step, index) => {
								const Icon = step.icon;
								return (
									<SpotlightCard key={step.title} className="p-6">
										<div className="flex flex-col gap-6">
											<div className="flex items-center justify-between">
												<span className="grid size-12 place-items-center rounded-xl border border-border bg-muted text-foreground">
													<Icon aria-hidden="true" />
												</span>
												<span className="font-mono text-sm text-muted-foreground">0{index + 1}</span>
											</div>
											<div className="flex flex-col gap-2">
												<h3 className="text-2xl font-semibold tracking-tight">{step.title}</h3>
												<p className="text-sm leading-6 text-muted-foreground">{step.description}</p>
											</div>
										</div>
									</SpotlightCard>
								);
							})}
						</div>
					</MarketingContainer>
				</section>

				<section id="analytics" className="border-b border-border/80 bg-background py-16 sm:py-24">
					<MarketingContainer className="grid gap-8 lg:grid-cols-[minmax(0,0.9fr)_minmax(420px,0.55fr)] lg:items-stretch">
						<SpotlightCard className="overflow-hidden p-0">
							<div className="border-b border-border p-6 sm:p-8">
								<h2 className="text-3xl font-semibold tracking-[-0.04em] sm:text-5xl">
									Know what worked before the next post goes out.
								</h2>
								<p className="mt-4 max-w-2xl text-base leading-7 text-muted-foreground">
									Dashboard views stay operational. Analytics goes deeper with post tables, audience readiness, account comparisons, and clear unavailable states.
								</p>
							</div>
							<div className="grid gap-3 p-6 sm:grid-cols-2 sm:p-8">
								{analyticsCards.map((item) => (
									<div key={item.label} className="rounded-xl border border-border bg-muted/55 p-4">
										<p className="text-sm font-medium text-muted-foreground">{item.label}</p>
										<p className="mt-2 text-4xl font-semibold tracking-[-0.05em]">{item.value}</p>
										<p className="mt-3 text-sm text-muted-foreground">{item.detail}</p>
									</div>
								))}
							</div>
							<div className="border-t border-border bg-muted/35 p-6 sm:p-8">
								<div className="h-48 rounded-2xl border border-border bg-card p-5">
									<div className="flex h-full items-end gap-3">
										{[28, 42, 36, 61, 48, 72, 58, 84, 66].map((height, index) => (
											<div key={index} className="flex flex-1 flex-col justify-end">
												<div
													className="rounded-t-lg bg-[color-mix(in_srgb,var(--color-chart-3)_76%,var(--color-card))]"
													style={{ height: `${height}%` }}
												/>
											</div>
										))}
									</div>
								</div>
							</div>
						</SpotlightCard>

						<SpotlightCard className="flex flex-col justify-between bg-[color-mix(in_srgb,var(--color-foreground)_92%,black)] p-7 text-primary-foreground">
							<div className="flex flex-col gap-6">
								<div className="flex items-center justify-between gap-4">
									<Sparkles aria-hidden="true" className="text-primary" />
									<Badge tone="outline" className="border-primary/40 text-primary-foreground">
										Layer-ready
									</Badge>
								</div>
								<blockquote className="text-2xl font-semibold leading-snug tracking-tight">
									“Juno33 replaced five different tools for us. Our team moves faster and our content performs better.”
								</blockquote>
							</div>
							<div className="mt-12 flex items-center justify-between gap-4 border-t border-white/10 pt-6">
								<div>
									<p className="font-semibold">Lena Martinez</p>
									<p className="text-sm text-white/55">Head of Social, Layer</p>
								</div>
								<div className="text-right text-sm text-white/60">
									<p>SOC 2 Type II</p>
									<p>99.9% uptime</p>
								</div>
							</div>
						</SpotlightCard>
					</MarketingContainer>
				</section>

				<section id="pricing" className="border-b border-border/80 py-16 sm:py-24">
					<MarketingContainer className="grid gap-8 lg:grid-cols-[minmax(0,0.75fr)_minmax(420px,0.55fr)] lg:items-start">
						<div className="flex max-w-3xl flex-col gap-5">
							<h2 className="text-3xl font-semibold tracking-[-0.04em] sm:text-5xl">
								Start with the operating system your social team actually needs.
							</h2>
							<p className="text-base leading-7 text-muted-foreground sm:text-lg">
								Bring planning, publishing, inbox, and analytics into one place before adding more accounts, automations, and reporting workflows.
							</p>
							<div className="grid gap-3 sm:grid-cols-3">
								{["No card to explore", "Team-ready workspace", "Upgrade when the fleet grows"].map((item) => (
									<div key={item} className="flex items-center gap-2 text-sm font-medium">
										<Check aria-hidden="true" className="text-primary" />
										<span>{item}</span>
									</div>
								))}
							</div>
						</div>
						<SpotlightCard className="p-6 sm:p-8">
							<div className="flex items-start justify-between gap-4">
								<div>
									<p className="text-sm font-medium text-muted-foreground">Team workspace</p>
									<p className="mt-2 text-5xl font-semibold tracking-[-0.06em]">Start free</p>
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

				<section className="bg-background py-16 sm:py-24">
					<MarketingContainer className="grid gap-8 lg:grid-cols-[minmax(260px,0.45fr)_minmax(0,0.75fr)]">
						<div>
							<h2 className="text-3xl font-semibold tracking-[-0.04em]">Questions teams ask before switching.</h2>
							<p className="mt-4 text-base leading-7 text-muted-foreground">
								The short version: Juno33 is built for teams managing many social accounts, not solo posting from a phone.
							</p>
						</div>
						<Accordion type="single" collapsible className="rounded-2xl border border-border bg-card px-5">
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
				<MarketingContainer className="flex flex-col gap-5 py-8 sm:flex-row sm:items-center sm:justify-between">
					<div className="flex items-center gap-3 font-semibold">
						<span className="grid size-8 place-items-center rounded-lg border border-border bg-card text-primary">
							<span className="size-3.5 rotate-45 rounded-[3px] border-2 border-current" />
						</span>
						Juno33
					</div>
					<div className="flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
						<Link to="/login" className="hover:text-foreground">Sign in</Link>
						<Link to="/signup" className="hover:text-foreground">Start free</Link>
						<Link to="/privacy" className="hover:text-foreground">Privacy</Link>
						<Link to="/terms" className="hover:text-foreground">Terms</Link>
					</div>
				</MarketingContainer>
			</footer>
		</MarketingShell>
	);
}
