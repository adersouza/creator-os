import type { Meta, StoryObj } from "@storybook/react-vite";
import { StatusPill } from "./StatusPill";

const meta = {
	title: "UI/StatusPill",
	component: StatusPill,
	parameters: {
		layout: "centered",
	},
} satisfies Meta<typeof StatusPill>;

export default meta;

type Story = StoryObj<typeof meta>;

export const AllTones: Story = {
	render: () => (
		<div
			data-testid="status-pill-visual"
			className="flex w-[520px] flex-wrap items-center gap-3 rounded-lg border border-border bg-background p-5"
		>
			<StatusPill tone="ink">Selected</StatusPill>
			<StatusPill tone="info">Queued</StatusPill>
			<StatusPill tone="good" dot>
				Ready
			</StatusPill>
			<StatusPill tone="warn" dot>
				Review
			</StatusPill>
			<StatusPill tone="critical" dot>
				Blocked
			</StatusPill>
			<StatusPill tone="idle" dot>
				Idle
			</StatusPill>
			<StatusPill tone="oxblood" live dot>
				Live
			</StatusPill>
			<StatusPill tone="ghost">Ghost</StatusPill>
		</div>
	),
};

