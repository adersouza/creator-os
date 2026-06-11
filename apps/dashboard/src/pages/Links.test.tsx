import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Links } from "./Links";

const smartLinksState = vi.hoisted(() => ({
	links: [
		{
			id: "link-1",
			code: "launch",
			title: "Launch link",
			targetUrl: "https://example.com",
			clickCount: 42,
			isActive: true,
			postId: null,
			createdAt: "2026-06-01T00:00:00.000Z",
			updatedAt: "2026-06-02T00:00:00.000Z",
			utm: null,
			theme: "ink",
			items: [],
			blocks: [],
			metadata: null,
		},
	],
	isLoading: false,
	createLink: vi.fn(),
	updateLink: vi.fn(),
	deleteLink: vi.fn(),
	refetch: vi.fn(),
}));

const goalState = vi.hoisted(() => ({
	saveGoal: vi.fn(async () => undefined),
}));

vi.mock("@/hooks/useSmartLinks", () => ({
	useSmartLinks: () => smartLinksState,
}));

vi.mock("@/hooks/useSmartLinkClickGoal", () => ({
	useSmartLinkClickGoal: () => ({
		goal: { targetClicks: 200, periodDays: 30, enabled: true },
		saveGoal: goalState.saveGoal,
		isLoading: false,
		hasError: false,
	}),
	useSmartLinkClickSummary: () => ({
		totalClicks: 84,
		periodDays: 30,
		topLink: { id: "link-1", code: "launch", title: "Launch link", clicks: 84 },
		linkCount: 1,
		isLoading: false,
		hasError: false,
	}),
}));

vi.mock("@/components/links/LinkRow", () => ({
	LinkRow: ({ link, onClick }: { link: { code: string }; onClick: () => void }) => (
		<button type="button" onClick={onClick}>
			/{link.code}
		</button>
	),
}));

vi.mock("@/components/links/LinkDetailPane", () => ({
	LinkDetail: () => <div>Link detail</div>,
}));

vi.mock("@/components/links/EmptyDetail", () => ({
	EmptyDetail: () => <div>No active link</div>,
}));

vi.mock("@/components/links/LinkPagePreview", () => ({
	MobileLinkPreviewOverlay: () => null,
}));

vi.mock("@/components/skeletons/PageSkeletons", () => ({
	SmartLinksSkeleton: () => <div>Loading smart links</div>,
}));

describe("Links page widget summary", () => {
	beforeEach(() => {
		goalState.saveGoal.mockClear();
	});

	it("renders click goal and link health through the widget foundation", async () => {
		const { container } = render(
			<MemoryRouter initialEntries={["/links"]}>
				<Links />
			</MemoryRouter>,
		);

		expect(screen.getByText("Click goal")).toBeInTheDocument();
		expect(screen.getByText("Link health")).toBeInTheDocument();
		expect(screen.getByText("84")).toBeInTheDocument();
		expect(screen.getByText("1 total")).toBeInTheDocument();
		expect(container.querySelectorAll(".nova-card").length).toBeGreaterThanOrEqual(2);
		expect(container.querySelectorAll(".nova-data-panel").length).toBeGreaterThanOrEqual(1);
		expect(screen.getByText("Active links")).toBeInTheDocument();
		expect(screen.getByText("Clicks all-time")).toBeInTheDocument();
		expect(screen.getByText("Top performer")).toBeInTheDocument();
		expect(screen.getByText("Avg per link")).toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: "Save goal" }));

		await waitFor(() => {
			expect(goalState.saveGoal).toHaveBeenCalledWith({
				targetClicks: 200,
				periodDays: 30,
				enabled: true,
			});
		});
	});
});
