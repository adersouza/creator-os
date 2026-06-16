import { Outlet } from "react-router-dom";
import { BarChart3, CheckCircle2, MessageSquareReply, PenLine } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import {
	Card,
	CardAction,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/Card";
import { Separator } from "@/components/ui/Separator";

const AUTH_FEATURES = [
	"Manage unlimited accounts",
	"AI content that matches your voice",
	"Auto-replies that convert",
	"Analytics that prove impact",
];

const AUTH_STATS = [
	{ label: "Views", value: "124k" },
	{ label: "Replies", value: "8.4k" },
	{ label: "Posts", value: "1.2k" },
];

const AUTH_ACTIONS = [
	{ label: "Plan next post", detail: "Best window opens at 2:30 PM", Icon: PenLine },
	{ label: "Reply queue", detail: "12 conversations need review", Icon: MessageSquareReply },
	{ label: "Analytics", detail: "Reach is up 18% this week", Icon: BarChart3 },
];

export function AuthLayout() {
	return (
		<div className="min-h-[100dvh] bg-background text-foreground">
			<div className="flex min-h-[100dvh] items-center justify-center px-4 py-6 sm:p-6">
				<div className="auth-layout-shell grid h-auto w-full max-w-sm self-center overflow-hidden rounded-xl border border-border bg-card shadow-sm md:max-h-[calc(100dvh-3rem)] md:max-w-5xl md:grid-cols-[minmax(23rem,0.9fr)_minmax(0,1.1fr)]">
					<div className="flex min-w-0 items-center justify-center p-4 sm:p-8 [&_.auth-card]:border-0 [&_.auth-card]:bg-transparent [&_.auth-card]:shadow-none">
						<Outlet />
					</div>

					<section
						className="relative hidden min-h-[36rem] overflow-hidden border-l border-border bg-muted p-8 md:block"
						aria-label="Juno33 product summary"
					>
						<div className="flex h-full flex-col justify-between gap-8">
							<div className="flex items-center justify-between gap-4">
								<div
									className="inline-flex items-baseline gap-0.5 text-sm font-semibold uppercase tracking-[0.16em] text-foreground"
									role="img"
									aria-label="Juno33"
								>
									<span>Juno</span>
									<strong className="text-primary">33</strong>
								</div>
								<Badge tone="outline">Secure workspace</Badge>
							</div>

							<div>
								<h2 className="max-w-[15ch] text-4xl font-semibold leading-tight tracking-normal text-foreground">
									One place for posts, replies, and proof.
								</h2>
								<p className="mt-4 max-w-sm text-sm leading-relaxed text-muted-foreground">
									Track what went live, see what performed, and keep the next action close without switching tools.
								</p>
								<div className="mt-6 grid gap-2">
									{AUTH_FEATURES.map((item) => (
										<div
											key={item}
											className="flex min-w-0 items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm leading-snug text-muted-foreground"
										>
											<CheckCircle2
												data-icon="inline-start"
												className="text-primary"
												aria-hidden="true"
											/>
											<span>{item}</span>
										</div>
									))}
								</div>
							</div>

							<Card className="bg-card" role="img" aria-label="Juno33 dashboard preview">
								<CardHeader className="p-4 pb-3">
									<div>
										<CardTitle>Today at a glance</CardTitle>
										<CardDescription>Performance and work queue</CardDescription>
									</div>
									<CardAction>
										<Badge tone="oxblood">Live</Badge>
									</CardAction>
								</CardHeader>
								<CardContent className="p-4 pt-0">
									<div className="grid gap-3">
										<div className="grid grid-cols-3 gap-2">
											{AUTH_STATS.map((stat) => (
												<div
													key={stat.label}
													className="rounded-lg border border-border bg-muted/45 p-3"
												>
													<div className="text-xl font-semibold tabular-nums text-foreground">
														{stat.value}
													</div>
													<div className="mt-1 truncate text-[0.6875rem] font-medium uppercase tracking-[0.12em] text-muted-foreground">
														{stat.label}
													</div>
												</div>
											))}
										</div>
										<Separator />
										<div className="grid gap-2">
											{AUTH_ACTIONS.map(({ label, detail, Icon }) => (
												<div
													key={label}
													className="grid grid-cols-[2rem_minmax(0,1fr)] items-center gap-3 rounded-lg border border-border bg-card px-3 py-2.5"
												>
													<div className="flex size-8 items-center justify-center rounded-md bg-muted text-primary">
														<Icon aria-hidden="true" />
													</div>
													<div className="min-w-0">
														<strong className="block truncate text-sm font-medium text-foreground">
															{label}
														</strong>
														<span className="block truncate text-xs text-muted-foreground">
															{detail}
														</span>
													</div>
												</div>
											))}
										</div>
									</div>
								</CardContent>
							</Card>
						</div>
					</section>
				</div>
			</div>
		</div>
	);
}
