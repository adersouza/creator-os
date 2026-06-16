import type { Meta, StoryObj } from "@storybook/react-vite";
import type { ColumnDef } from "@tanstack/react-table";
import {
	CalendarClock,
	CheckCircle2,
	Command,
	MessageSquare,
	Search,
	ShieldAlert,
	BadgeCheck,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { CommandMenuActionRow } from "@/components/ui/CommandMenuShell";
import { DataTable } from "@/components/ui/DataTable";
import {
	NovaBentoGrid,
	NovaCard,
	NovaInset,
	NovaListRow,
	NovaMiniStat,
	NovaStat,
} from "@/components/ui/NovaPrimitives";
import { UploadStatusList, UploadZone } from "@/components/ui/Upload";

const meta = {
	title: "Frontend Quality/Shared Patterns",
	parameters: {
		layout: "fullscreen",
		chromatic: { modes: { light: {}, dark: { theme: "dark" } } },
	},
	decorators: [
		(Story) => (
			<div className="min-h-screen bg-[var(--color-surface-frame)] p-6 text-foreground">
				<div className="mx-auto max-w-6xl">
					<Story />
				</div>
			</div>
		),
	],
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

const postRows = [
	{
		id: "post-1",
		caption: "The one launch detail everyone misses",
		account: "@lunaai",
		platform: "Threads",
		views: "8.2K",
		status: "Review",
	},
	{
		id: "post-2",
		caption: "How we planned the week in 12 minutes",
		account: "@juno33",
		platform: "Instagram",
		views: "12.4K",
		status: "Ready",
	},
];

const postColumns: ColumnDef<(typeof postRows)[number]>[] = [
	{
		accessorKey: "caption",
		header: "Post",
		cell: ({ row }) => (
			<div className="min-w-0">
				<div className="truncate font-semibold">{row.original.caption}</div>
				<div className="text-xs text-muted-foreground">{row.original.account}</div>
			</div>
		),
	},
	{ accessorKey: "platform", header: "Platform" },
	{ accessorKey: "views", header: "Views" },
	{
		accessorKey: "status",
		header: "Status",
		cell: ({ row }) => <Badge tone="outline">{row.original.status}</Badge>,
	},
];

function renderDashboardStats() {
	return (
		<NovaBentoGrid className="grid-cols-1 md:grid-cols-3">
			<NovaStat
				label="Views"
				value="42.8K"
				description="Best available views/reach signal."
				trend={{ direction: "up", label: "+12.4%" }}
				icon={<Search data-icon="stacked" aria-hidden="true" />}
			/>
			<NovaStat
				label="Engagement rate"
				value="5.8%"
				description="Interactions divided by views/reach."
				trend={{ direction: "flat", label: "Stable" }}
				icon={<MessageSquare data-icon="stacked" aria-hidden="true" />}
			/>
			<NovaStat
				label="Scheduled posts"
				value="9"
				description="Ready across the active scope."
				status={<Badge tone="secondary">Runway ready</Badge>}
				icon={<CalendarClock data-icon="stacked" aria-hidden="true" />}
			/>
		</NovaBentoGrid>
	);
}

export const DashboardStats: Story = {
	render: renderDashboardStats,
};

export const DashboardStatsDark: Story = {
	decorators: [
		(Story) => (
			<div className="dark min-h-screen bg-[var(--color-surface-frame)] p-6 text-foreground">
				<div className="mx-auto max-w-6xl">
					<Story />
				</div>
			</div>
		),
	],
	render: renderDashboardStats,
};

export const DenseTable: Story = {
	parameters: {
		viewport: { defaultViewport: "mobile1" },
	},
	render: () => (
		<DataTable
			ariaLabel="Recent posts"
			data={postRows}
			columns={postColumns}
			tableClassName="min-w-[720px]"
			toolbar={
				<>
					<div>
						<div className="text-sm font-semibold text-foreground">Recent Posts</div>
						<div className="text-xs text-muted-foreground">Operational content performance</div>
					</div>
					<Button size="sm" variant="outline">Export</Button>
				</>
			}
			footer={<span>2 posts shown</span>}
		/>
	),
};

export const UploadAndCommand: Story = {
	render: () => (
		<div className="grid gap-5 lg:grid-cols-2">
			<NovaCard title="Media upload" description="Blocks-style upload pattern behind Juno wrappers.">
				<UploadZone
					title="Drop campaign media"
					description="Images and videos stay attached to this workflow."
					helper="PNG, JPG, MP4 up to 50MB"
					actionLabel="Choose files"
				/>
				<UploadStatusList
					className="mt-4"
					items={[
						{
							id: "clip",
							name: "launch-clip.mp4",
							description: "Uploading to media library",
							status: "uploading",
							progress: 64,
						},
						{
							id: "cover",
							name: "cover.png",
							status: "done",
						},
					]}
				/>
			</NovaCard>
			<NovaCard title="Command rows" description="Grouped action rows for command palettes and slash menus.">
				<div className="grid gap-2">
					<CommandMenuActionRow
						icon={<Command data-icon="stacked" aria-hidden="true" />}
						label="Create post"
						description="Open Composer with current scope"
						shortcut="C"
					/>
					<CommandMenuActionRow
						icon={<Search data-icon="stacked" aria-hidden="true" />}
						label="Search conversations"
						description="Jump to Inbox and focus search"
						shortcut="I"
					/>
				</div>
			</NovaCard>
		</div>
	),
};

export const CalendarAndAccountDetail: Story = {
	render: () => (
		<div className="grid gap-5 lg:grid-cols-2">
			<NovaCard title="Calendar event" description="Readable event density and drag/drop state.">
				<div className="rounded-xl border border-border bg-card p-4">
					<div className="nova-calendar-event__content rounded-lg border border-border bg-muted/50 p-3">
						<div className="nova-calendar-event__meta">
							<span>9:30 AM</span>
							<span className="nova-calendar-event__platform">TH</span>
						</div>
						<div className="nova-calendar-event__title">
							Launch the weekly content thread
						</div>
						<div className="nova-calendar-event__account">@juno33</div>
					</div>
				</div>
			</NovaCard>
			<NovaCard title="Account detail" description="Provider identity plus actionable remediation.">
				<NovaInset>
					<div className="flex items-start gap-3">
						<span className="flex size-10 items-center justify-center rounded-xl border border-border bg-card text-muted-foreground">
							<BadgeCheck data-icon="stacked" aria-hidden="true" />
						</span>
						<div className="min-w-0">
							<div className="font-semibold">@lunaai</div>
							<div className="text-sm text-muted-foreground">Instagram · connected</div>
						</div>
					</div>
				</NovaInset>
				<div className="mt-4 grid gap-3 sm:grid-cols-2">
					<NovaMiniStat label="Readiness" value="Ready" trend="All checks passed" tone="success" />
					<NovaMiniStat label="Issues" value="1" trend="Needs review" tone="warning" />
				</div>
				<div className="mt-4 grid gap-2">
					<NovaListRow
						leading={<ShieldAlert data-icon="stacked" aria-hidden="true" />}
						title="Reconnect before publishing"
						description="Token expires soon. Refresh access to keep scheduled posts moving."
						action={<Button size="sm">Fix</Button>}
					/>
					<NovaListRow
						leading={<CheckCircle2 data-icon="stacked" aria-hidden="true" />}
						title="Profile data current"
						description="Avatar, handle, and platform metadata are available."
					/>
				</div>
			</NovaCard>
		</div>
	),
};
