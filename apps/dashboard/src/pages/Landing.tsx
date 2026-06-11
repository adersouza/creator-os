import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
	ArrowRight,
	BarChart3,
	CalendarDays,
	Camera,
	CheckCircle2,
	Clock,
	Library,
	MessageSquare,
	Radar,
	Send,
	Sparkles,
	Users,
} from "lucide-react";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import {
	NovaCard,
	NovaHeader,
	NovaSection,
	NovaStat,
} from "@/components/ui/NovaPrimitives";
import { Progress } from "@/components/ui/Progress";
import { Separator } from "@/components/ui/Separator";
import { supabaseAuth } from "@/services/supabase";

const WORKFLOW_CARDS = [
	{
		title: "Plan the posting week",
		description:
			"Draft, schedule, and rebalance every account from one publishing surface.",
		icon: CalendarDays,
		metric: "47",
		label: "scheduled posts",
	},
	{
		title: "Read content performance",
		description:
			"See what was posted, how it moved, and which creative patterns are working.",
		icon: Library,
		metric: "12.8k",
		label: "fleet reach",
	},
	{
		title: "Answer from one inbox",
		description:
			"Route replies, assignments, and held conversations without platform hopping.",
		icon: MessageSquare,
		metric: "4m",
		label: "median response",
	},
];

const SIGNAL_ROWS = [
	{ label: "Threads reply depth", value: "Strong", progress: 82 },
	{ label: "Instagram source mix", value: "Balanced", progress: 64 },
	{ label: "Schedule compliance", value: "At risk", progress: 42 },
];

const FEATURE_LIST = [
	"Multi-account content calendar",
	"AI caption drafts with approval controls",
	"Threads and Instagram analytics",
	"Unified inbox and assignment flow",
	"Workspace billing and access control",
	"Publishing readiness checks",
];

/**
 * Public marketing page at `/`.
 *
 * Logged-in users still redirect into the product. The previous landing page
 * was a static HTML/CSS/JS island; this version uses the same shadcn-backed
 * Juno wrappers as the rebuilt product surfaces.
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

	if (!checkedSession) {
		return null;
	}

	return (
		<div className="min-h-screen bg-background text-foreground">
			<NovaScreen width="wide" className="gap-10 py-5 md:py-8">
				<nav className="flex items-center justify-between gap-4">
					<Link
						to="/"
						className="flex items-center gap-2 text-sm font-semibold"
					>
						<span className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
							J
						</span>
						Juno33
					</Link>
					<div className="hidden items-center gap-2 md:flex">
						<Button variant="ghost" size="sm" asChild>
							<Link to="/login">Sign in</Link>
						</Button>
						<Button size="sm" asChild>
							<Link to="/signup">
								Start free
								<ArrowRight data-icon="inline-end" aria-hidden="true" />
							</Link>
						</Button>
					</div>
				</nav>

				<NovaSection className="grid gap-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(420px,0.95fr)] lg:items-stretch">
					<div className="flex min-w-0 flex-col justify-between gap-6">
						<NovaHeader
							eyebrow="Threads + Instagram operations"
							title="Run the content fleet from one clean command center."
							description="Juno33 brings planning, publishing, inbox triage, and evidence-grade analytics into one workspace for teams managing many social accounts."
							meta="shadcn/Nova product rebuild"
							actions={
								<>
									<Button asChild>
										<Link to="/signup">
											Create workspace
											<ArrowRight data-icon="inline-end" aria-hidden="true" />
										</Link>
									</Button>
									<Button variant="outline" asChild>
										<Link to="/login">Sign in</Link>
									</Button>
								</>
							}
						/>
						<div className="grid gap-3 sm:grid-cols-3">
							<NovaStat
								label="Accounts"
								value="276"
								description="Fleet-ready account scope"
								icon={<Users aria-hidden="true" />}
								variant="compact"
							/>
							<NovaStat
								label="Publishing"
								value="99%"
								description="Schedule compliance target"
								icon={<Send aria-hidden="true" />}
								progress={99}
								variant="compact"
							/>
							<NovaStat
								label="Signals"
								value="24h"
								description="Anomaly review window"
								icon={<Radar aria-hidden="true" />}
								variant="compact"
							/>
						</div>
					</div>

					<NovaCard
						title="Performance evidence"
						description="A Nova-style product preview using the same primitives as the app."
						action={<Badge tone="oxblood">Live preview</Badge>}
						footer={
							<div className="flex w-full flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
								<span>Evidence updates as the workspace posts.</span>
								<Button variant="outline" size="sm" asChild>
									<Link to="/signup">Open workspace</Link>
								</Button>
							</div>
						}
					>
						<div className="grid gap-3 sm:grid-cols-2">
							<div className="rounded-lg border border-border bg-muted/35 p-4">
								<div className="flex items-center justify-between gap-2">
									<div>
										<p className="text-sm font-medium text-muted-foreground">
											Fleet reach
										</p>
										<p className="mt-2 text-4xl font-semibold tracking-[-0.045em]">
											48.2k
										</p>
									</div>
									<BarChart3
										aria-hidden="true"
										className="text-muted-foreground"
									/>
								</div>
								<Progress value={72} className="mt-5" />
							</div>
							<div className="rounded-lg border border-border bg-muted/35 p-4">
								<div className="flex items-center justify-between gap-2">
									<div>
										<p className="text-sm font-medium text-muted-foreground">
											Approval queue
										</p>
										<p className="mt-2 text-4xl font-semibold tracking-[-0.045em]">
											18
										</p>
									</div>
									<Clock aria-hidden="true" className="text-muted-foreground" />
								</div>
								<Progress value={44} className="mt-5" />
							</div>
						</div>
						<div className="mt-4 flex flex-col gap-3">
							{SIGNAL_ROWS.map((row) => (
								<div
									key={row.label}
									className="rounded-lg border border-border bg-background p-3"
								>
									<div className="flex items-center justify-between gap-3">
										<span className="text-sm font-medium">{row.label}</span>
										<Badge
											tone={row.value === "At risk" ? "danger" : "secondary"}
										>
											{row.value}
										</Badge>
									</div>
									<Progress value={row.progress} className="mt-3" />
								</div>
							))}
						</div>
					</NovaCard>
				</NovaSection>

				<NovaSection className="grid gap-4 md:grid-cols-3">
					{WORKFLOW_CARDS.map((item) => {
						const Icon = item.icon;
						return (
							<NovaCard
								key={item.title}
								title={item.title}
								description={item.description}
							>
								<div className="flex items-end justify-between gap-4">
									<div>
										<p className="text-3xl font-semibold tracking-[-0.04em]">
											{item.metric}
										</p>
										<p className="mt-1 text-sm text-muted-foreground">
											{item.label}
										</p>
									</div>
									<div className="flex size-10 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
										<Icon aria-hidden="true" />
									</div>
								</div>
							</NovaCard>
						);
					})}
				</NovaSection>

				<NovaSection className="grid gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(360px,0.55fr)]">
					<NovaCard
						eyebrow="What replaces platform hopping"
						title="Plan, publish, respond, and analyze without losing context."
						description="The product surface is designed for operators who need to understand what happened, why it happened, and what to do next."
					>
						<div className="grid gap-3 sm:grid-cols-2">
							{FEATURE_LIST.map((feature) => (
								<div
									key={feature}
									className="flex items-center gap-3 rounded-lg border border-border bg-background p-3"
								>
									<CheckCircle2
										aria-hidden="true"
										className="shrink-0 text-primary"
									/>
									<span className="text-sm font-medium">{feature}</span>
								</div>
							))}
						</div>
					</NovaCard>

					<NovaCard
						title="Get the walkthrough"
						description="Tell us where to send the product briefing."
						action={<Badge tone="outline">No spam</Badge>}
					>
						<form className="flex flex-col gap-3" action="/signup">
							<Input
								type="email"
								name="email"
								placeholder="operator@company.com"
								leadingIcon={<Sparkles aria-hidden="true" />}
								autoComplete="email"
							/>
							<Button type="submit">
								Continue
								<ArrowRight data-icon="inline-end" aria-hidden="true" />
							</Button>
						</form>
						<Separator className="my-5" />
						<div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
							<Camera aria-hidden="true" />
							<span>Built for Threads and Instagram operating teams.</span>
						</div>
					</NovaCard>
				</NovaSection>
			</NovaScreen>
		</div>
	);
}
