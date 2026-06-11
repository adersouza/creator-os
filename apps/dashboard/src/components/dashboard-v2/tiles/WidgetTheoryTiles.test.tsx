import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AIEvalSummaryTile, FleetCapacityTile } from "./ManagerReadinessTile";
import { OpsHealthTile } from "./OpsHealthTile";

const navigateMock = vi.hoisted(() => vi.fn());
const refetchMock = vi.hoisted(() => vi.fn());

const snapshot = {
	opsHealth: {
		score: 91,
		tone: "warning",
		metrics: [
			{ key: "cron", label: "Cron", value: "OK", status: "healthy", route: "/reliability?panel=cron" },
			{ key: "tokens", label: "Tokens", value: 2, status: "warning", route: "/accounts?status=tokens" },
		],
		issues: [
			{
				key: "qstash",
				title: "QStash retries elevated",
				severity: "warning",
				source: "qstash",
				route: "/reliability?panel=qstash",
			},
		],
		unhealthyAccounts: [
			{
				accountId: "acct_1",
				handle: "juno",
				platform: "threads",
				severity: "warning",
				reasons: ["token expiring"],
				route: "/accounts/acct_1",
			},
		],
	},
	fleetCapacity: {
		tone: "healthy",
		activeAccountCount: 12,
		days: [
			{
				date: "2026-06-03",
				scheduled: 4,
				pendingQueue: 1,
				failed: 0,
				deadLetter: 0,
				tone: "healthy",
				accountIds: ["acct_1"],
			},
			{
				date: "2026-06-04",
				scheduled: 2,
				pendingQueue: 0,
				failed: 1,
				deadLetter: 0,
				tone: "warning",
				accountIds: ["acct_1"],
			},
		],
	},
	aiEvalSummary: {
		tone: "warning",
		windowDays: 14,
		total: 20,
		passed: 18,
		failed: 2,
		passRate: 90,
		trend: [
			{ day: "2026-06-01", suiteName: "live:composer", surface: "composer", passRate: 90, failed: 1 },
		],
		suites: [
			{ suiteName: "live:composer", surface: "composer", total: 10, failed: 1, passRate: 90 },
		],
		latestFailures: [],
		thresholds: { failures: [] },
		coverage: {
			directGenerativeSurfaceCount: 2,
			directGenerativeCoveredCount: 1,
			documentedNonGenerativeCount: 3,
			uncoveredDirectSurfaces: ["ideas"],
		},
	},
};

vi.mock("react-router-dom", () => ({
	useNavigate: () => navigateMock,
}));

vi.mock("@/hooks/useOperatorSnapshot", () => ({
	useOperatorSnapshot: () => ({
		snapshot,
		isLoading: false,
		hasError: false,
		refetch: refetchMock,
	}),
}));

describe("dashboard widget theory tiles", () => {
	it("renders ops health with shared metric and panel anatomy", () => {
		render(<OpsHealthTile scopeLabel="All accounts" />);

		expect(screen.getByText("Account issues")).toBeInTheDocument();
		expect(screen.getByText("Cron")).toBeInTheDocument();
		expect(screen.getByText("Unhealthy accounts")).toBeInTheDocument();
		expect(screen.getByText("@juno")).toBeInTheDocument();
		expect(screen.getByText("QStash retries elevated")).toBeInTheDocument();
	});

	it("renders readiness tiles without real operator data fetching", () => {
		render(
			<div>
				<FleetCapacityTile scopeLabel="All accounts" />
				<AIEvalSummaryTile />
			</div>,
		);

		expect(screen.getByText("Posting coverage")).toBeInTheDocument();
		expect(screen.getByText("AI readiness")).toBeInTheDocument();
		expect(screen.getByText("Passed")).toBeInTheDocument();
		expect(screen.getAllByText("composer").length).toBeGreaterThan(0);
	});
});
