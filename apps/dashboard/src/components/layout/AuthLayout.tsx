import { Outlet } from "react-router-dom";
import {
	BarChart3,
	CheckCircle2,
	LockKeyhole,
	ShieldCheck,
	Sparkles,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/Card";

export function AuthLayout() {
	return (
		<div className="dark min-h-[100dvh] bg-background text-foreground">
			<div className="flex min-h-[100dvh] items-center justify-center px-4 py-8 sm:p-6">
				<div className="grid w-full max-w-5xl overflow-hidden rounded-xl border border-border bg-card shadow-sm md:grid-cols-[minmax(0,1.12fr)_minmax(21rem,27rem)]">
					<section
						className="relative hidden min-h-[39rem] flex-col justify-between overflow-hidden border-r border-border bg-card p-8 md:flex"
						aria-label="Juno33 product summary"
					>
						<div
							className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.025)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[length:44px_44px] opacity-60"
							aria-hidden="true"
						/>
						<div className="relative z-10 inline-flex items-baseline gap-0.5 text-sm font-semibold uppercase tracking-[0.16em] text-foreground" role="img" aria-label="Juno33">
							<span>Juno</span>
							<strong className="text-primary">33</strong>
						</div>

						<div className="relative z-10">
							<h2 className="max-w-[15ch] text-3xl font-medium leading-tight tracking-tight text-foreground">
								The operating system for Threads & Instagram operators.
							</h2>
							<ul className="mt-6 grid gap-2.5 text-sm leading-snug text-muted-foreground">
								{[
									"Manage unlimited accounts",
									"AI content that matches your voice",
									"Auto-replies that convert",
									"Analytics that prove impact",
									"Built for operators, not agencies",
								].map((item) => (
									<li key={item} className="flex items-center gap-2">
										<CheckCircle2 className="h-4 w-4 text-primary" aria-hidden="true" />
										<span>{item}</span>
									</li>
								))}
							</ul>
						</div>

						<Card
							className="relative z-10 w-full max-w-sm bg-muted/30"
							role="img"
							aria-label="Juno33 dashboard preview"
						>
							<CardHeader>
								<div>
									<CardTitle>Performance command</CardTitle>
									<CardDescription>Live workspace overview</CardDescription>
								</div>
								<Badge variant="secondary">Demo</Badge>
							</CardHeader>
							<CardContent>
								<div className="grid grid-cols-[3rem_minmax(0,1fr)] overflow-hidden rounded-lg border border-border bg-card">
									<div className="grid content-start gap-2 border-r border-border p-3">
										{Array.from({ length: 6 }).map((_, index) => (
											<span key={index} className="h-2 rounded-full bg-muted" />
										))}
									</div>
									<div className="grid gap-3 p-3">
										<div className="grid grid-cols-3 gap-2">
											<span className="h-8 rounded-md border border-border bg-muted/50" />
											<span className="h-8 rounded-md border border-border bg-muted/50" />
											<span className="h-8 rounded-md border border-border bg-muted/50" />
										</div>
										<div className="flex h-14 items-center justify-center rounded-md bg-primary/10 text-primary">
											<BarChart3 className="h-7 w-7" aria-hidden="true" />
										</div>
										<div className="grid grid-cols-3 gap-2">
											<span className="h-8 rounded-md border border-border bg-muted/50" />
											<span className="h-8 rounded-md border border-border bg-muted/50" />
											<span className="h-8 rounded-md border border-border bg-muted/50" />
										</div>
									</div>
								</div>
							</CardContent>
						</Card>

						<div className="relative z-10 grid grid-cols-4 gap-3">
							{[
								{ label: "SOC 2", detail: "Type II", Icon: ShieldCheck },
								{ label: "GDPR", detail: "Compliant", Icon: CheckCircle2 },
								{ label: "OAuth 2.0", detail: "Secure", Icon: Sparkles },
								{ label: "256-bit", detail: "Encryption", Icon: LockKeyhole },
							].map(({ label, detail, Icon }) => (
								<div key={label} className="min-w-0 text-center">
									<Icon className="mx-auto mb-2 h-7 w-7 rounded-full bg-muted p-1.5 text-muted-foreground" aria-hidden="true" />
									<strong className="block truncate text-xs font-medium text-foreground">
										{label}
									</strong>
									<span className="block truncate text-[0.6875rem] text-muted-foreground">
										{detail}
									</span>
								</div>
							))}
						</div>
					</section>

					<div className="flex min-w-0 items-center justify-center bg-card p-4 sm:p-8">
						<Outlet />
					</div>
				</div>
			</div>
		</div>
	);
}
