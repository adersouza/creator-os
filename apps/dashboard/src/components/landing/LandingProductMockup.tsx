import type React from "react";
import {
	BarChart3,
	CalendarDays,
	Check,
	Inbox,
	Library,
	Plus,
	Search,
	Send,
	Settings,
	Sparkles,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { Button } from "@/components/ui/Button";
import { BorderBeam } from "./LandingEffects";

const commandRows = [
	{ label: "Create new post", hint: "Compose and schedule content", key: "N", icon: Send },
	{ label: "Open inbox", hint: "View and reply to messages", key: "I", icon: Inbox },
	{ label: "View analytics", hint: "Explore performance insights", key: "A", icon: BarChart3 },
	{ label: "Search posts", hint: "Find content by keyword or status", key: "F", icon: Search },
];

const stats = [
	{ label: "Followers", value: "24,812", delta: "+2.2%" },
	{ label: "Impressions", value: "512K", delta: "+8.7%" },
	{ label: "Engagement", value: "3.6%", delta: "+0.6%" },
	{ label: "Profile visits", value: "17.6K", delta: "+5.1%" },
];

const posts = [
	{ title: "New product drop is here", platform: "instagram", reach: "12.4K", status: "Scheduled" },
	{ title: "Behind the scenes at Acme", platform: "threads", reach: "8.7K", status: "Published" },
	{ title: "Customer spotlight: Lumi", platform: "instagram", reach: "9.1K", status: "Published" },
] as const;

const inbox = [
	{ name: "jessica.walsh", text: "Hey! Love the new drop", time: "2m" },
	{ name: "matt.designs", text: "Is this available in EU?", time: "12m" },
	{ name: "the.visual.diary", text: "So clean", time: "1h" },
];

export function LandingProductMockup() {
	return (
		<div className="landing-mockup relative isolate mx-auto w-full max-w-[920px]">
			<div
				data-landing-product-frame
				className="relative z-10 overflow-hidden rounded-2xl border border-white/15 bg-[oklch(0.12_0.006_285.885)] text-white shadow-[0_30px_90px_rgba(0,0,0,0.38)] ring-1 ring-black/25"
			>
				<BorderBeam />
				<div
					aria-hidden="true"
					className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_68%_14%,rgba(255,255,255,0.1),transparent_34%),linear-gradient(90deg,rgba(0,0,0,0.28),transparent_32%,transparent_68%,rgba(0,0,0,0.18))]"
				/>
				<div className="grid min-h-[520px] grid-cols-[180px_minmax(0,1fr)_210px] max-lg:grid-cols-[150px_minmax(0,1fr)] max-md:min-h-0 max-md:grid-cols-1">
					<aside className="relative z-10 flex flex-col gap-5 border-r border-white/10 bg-black/45 p-4 max-md:hidden">
						<div className="flex items-center gap-2 text-sm font-semibold">
							<span className="flex size-7 items-center justify-center rounded-md border border-white/15 bg-primary text-primary-foreground">
								J
							</span>
							Juno33
						</div>
						<div className="rounded-lg border border-white/12 bg-white/[0.08] p-3">
							<p className="text-sm font-medium">Acme Social</p>
							<p className="mt-1 text-xs text-white/72">Team workspace</p>
						</div>
						<nav className="flex flex-col gap-1 text-sm text-white/82">
							<MockNavItem active icon={<BarChart3 aria-hidden="true" />} label="Overview" />
							<MockNavItem icon={<CalendarDays aria-hidden="true" />} label="Calendar" />
							<MockNavItem icon={<Library aria-hidden="true" />} label="Content" />
							<MockNavItem icon={<Inbox aria-hidden="true" />} label="Inbox" badge="24" />
							<MockNavItem icon={<Settings aria-hidden="true" />} label="Settings" />
						</nav>
					</aside>

					<main className="relative z-10 min-w-0 p-4 sm:p-5">
						<div className="mb-4 flex items-center justify-between gap-3">
							<div>
								<p className="text-sm font-semibold">Overview</p>
								<p className="text-xs text-white/72">Live workspace command center</p>
							</div>
							<div className="flex items-center gap-2">
								<Button size="sm" variant="secondary" className="border-white/14 bg-white/[0.14] text-white hover:bg-white/[0.2]">
									Last 30 days
								</Button>
								<Button size="sm">
									<Plus data-icon="inline-start" aria-hidden="true" />
									New post
								</Button>
							</div>
						</div>

						<div className="relative z-10 mx-auto mb-4 max-w-[520px] rounded-xl border border-white/16 bg-[oklch(0.17_0.006_285.885)] p-2 shadow-2xl">
							<div className="mb-2 flex items-center gap-2 rounded-lg border border-white/14 bg-white/[0.1] px-3 py-2 text-sm text-white/90">
								<Search aria-hidden="true" />
								<span>Search Juno33...</span>
								<span className="ml-auto rounded border border-white/14 px-1.5 py-0.5 text-xs text-white/68">⌘ K</span>
							</div>
							<div className="flex flex-col gap-1">
								{commandRows.map((row, index) => {
									const Icon = row.icon;
									return (
										<div
											key={row.label}
											className={`flex items-center gap-3 rounded-lg px-3 py-2 ${index === 0 ? "bg-white/[0.13]" : "bg-transparent"}`}
										>
											<span className="flex size-8 items-center justify-center rounded-md bg-white/[0.13] text-white/90">
												<Icon aria-hidden="true" />
											</span>
											<div className="min-w-0">
												<p className="truncate text-sm font-medium">{row.label}</p>
												<p className="truncate text-xs text-white/72">{row.hint}</p>
											</div>
											<span className="ml-auto text-xs text-white/64">⌘ {row.key}</span>
										</div>
									);
								})}
							</div>
						</div>

						<div className="grid gap-3 sm:grid-cols-4">
							{stats.map((stat) => (
								<div key={stat.label} className="rounded-xl border border-white/14 bg-white/[0.085] p-3">
									<p className="text-[0.68rem] font-medium text-white/72">{stat.label}</p>
									<p className="mt-2 text-xl font-semibold tracking-tight">{stat.value}</p>
									<p className="mt-1 text-xs text-[color-mix(in_srgb,var(--color-success)_82%,white)]">{stat.delta} vs. prior</p>
									<div className="mt-3 h-6 rounded bg-[linear-gradient(135deg,transparent_15%,color-mix(in_srgb,var(--color-primary)_70%,transparent)_16%,transparent_18%,transparent_42%,color-mix(in_srgb,var(--color-primary)_52%,transparent)_44%,transparent_46%)]" />
								</div>
							))}
						</div>

						<div className="mt-3 rounded-xl border border-white/14 bg-white/[0.085] p-3">
							<div className="mb-3 flex items-center justify-between">
								<p className="text-sm font-semibold">Recent posts</p>
								<Badge tone="outline" className="border-white/12 text-white/75">View all</Badge>
							</div>
							<div className="flex flex-col gap-2">
								{posts.map((post) => (
									<div key={post.title} className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 rounded-lg border border-white/14 bg-black/35 p-2 text-sm">
										<div className="flex min-w-0 items-center gap-2">
											<BrandLogo name={post.platform} size="sm" />
											<span className="truncate font-medium">{post.title}</span>
										</div>
										<Badge tone="secondary" className="border-white/12 bg-white/[0.12] text-white/78">{post.status}</Badge>
										<span className="text-xs text-white/65">{post.reach}</span>
									</div>
								))}
							</div>
						</div>
					</main>

					<aside className="relative z-10 border-l border-white/10 bg-black/32 p-4 max-lg:hidden">
						<div className="rounded-xl border border-white/14 bg-white/[0.085] p-3">
							<div className="mb-3 flex items-center justify-between">
								<p className="text-sm font-semibold">Calendar</p>
								<Badge tone="outline" className="border-white/12 text-white/75">Today</Badge>
							</div>
							<div className="grid grid-cols-7 gap-1 text-center text-xs text-white/62">
								{["M", "T", "W", "T", "F", "S", "S"].map((day, index) => (
									<span key={`${day}-${index}`}>{day}</span>
								))}
							</div>
							<div className="mt-2 grid grid-cols-7 gap-1 text-center text-xs">
								{Array.from({ length: 14 }, (_, index) => (
									<span
										key={index}
										className={`rounded-md py-1 ${index === 4 ? "bg-primary text-primary-foreground" : "bg-white/[0.09] text-white/74"}`}
									>
										{index + 20}
									</span>
								))}
							</div>
							<div className="mt-3 flex flex-col gap-2">
								{["Product drop", "Behind the scenes", "Customer spotlight"].map((item, index) => (
									<div key={item} className="rounded-lg border border-white/14 bg-black/35 p-2">
										<p className="text-xs text-white/72">{index === 0 ? "9:00 AM" : index === 1 ? "12:30 PM" : "3:45 PM"}</p>
										<p className="mt-1 text-sm font-medium">{item}</p>
										<p className="mt-1 text-xs text-[color-mix(in_srgb,var(--color-success)_82%,white)]">Scheduled</p>
									</div>
								))}
							</div>
						</div>
					</aside>
				</div>
			</div>

			<div className="absolute -bottom-14 right-4 w-[280px] rounded-2xl border border-border bg-card p-4 text-card-foreground shadow-2xl max-lg:hidden">
				<div className="mb-3 flex items-center justify-between">
					<p className="font-semibold">Inbox</p>
					<Badge tone="oxblood">Live</Badge>
				</div>
				<div className="flex flex-col gap-2">
					{inbox.map((item) => (
						<div key={item.name} className="flex items-start gap-3 rounded-lg bg-muted/60 p-2">
							<span className="flex size-8 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
								{item.name.charAt(0).toUpperCase()}
							</span>
							<div className="min-w-0 flex-1">
								<p className="truncate text-sm font-medium">{item.name}</p>
								<p className="truncate text-xs text-muted-foreground">{item.text}</p>
							</div>
							<span className="text-xs text-muted-foreground">{item.time}</span>
						</div>
					))}
				</div>
				<Button className="mt-3 w-full" size="sm" variant="secondary">
					View conversations
				</Button>
			</div>
		</div>
	);
}

function MockNavItem({
	icon,
	label,
	active = false,
	badge,
}: {
	icon: React.ReactNode;
	label: string;
	active?: boolean | undefined;
	badge?: string | undefined;
}) {
	return (
		<div className={`flex items-center gap-2 rounded-md px-3 py-2 ${active ? "bg-white/[0.13] text-white" : ""}`}>
			<span className="text-white/75">{icon}</span>
			<span>{label}</span>
			{badge ? (
				<span className="ml-auto rounded-full bg-primary px-1.5 py-0.5 text-[0.65rem] font-semibold text-primary-foreground">
					{badge}
				</span>
			) : null}
		</div>
	);
}
