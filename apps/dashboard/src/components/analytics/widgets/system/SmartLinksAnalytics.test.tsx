import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SmartLinksAnalytics } from "./SmartLinksAnalytics";

const smartLinksState = vi.hoisted(() => ({
	links: [] as Array<{
		id: string;
		code: string;
		clickCount: number;
		isActive: boolean;
	}>,
	isLoading: false,
}));

vi.mock("@/hooks/useSmartLinks", () => ({
	useSmartLinks: () => smartLinksState,
}));

function renderWidget() {
	return render(
		<MemoryRouter>
			<SmartLinksAnalytics />
		</MemoryRouter>,
	);
}

describe("SmartLinksAnalytics", () => {
	beforeEach(() => {
		smartLinksState.links = [];
		smartLinksState.isLoading = false;
	});

	it("renders loading skeleton rows", () => {
		smartLinksState.isLoading = true;

		const { container } = renderWidget();

		expect(screen.getByText("Top clicked links")).toBeInTheDocument();
		expect(container.querySelectorAll(".td-surface-subtle").length).toBeGreaterThan(0);
	});

	it("renders ranked active links and top performer tag", () => {
		smartLinksState.links = [
			{ id: "a", code: "alpha", clickCount: 18, isActive: true },
			{ id: "b", code: "beta", clickCount: 6, isActive: true },
			{ id: "c", code: "inactive", clickCount: 22, isActive: false },
		];

		renderWidget();

		expect(screen.getAllByText("/alpha").length).toBeGreaterThan(0);
		expect(screen.getByText("/beta")).toBeInTheDocument();
		expect(screen.queryByText("/inactive")).not.toBeInTheDocument();
		expect(screen.getByText("Top performer")).toBeInTheDocument();
	});

	it("shows an empty state when loaded with no clicked active links", () => {
		smartLinksState.links = [
			{ id: "a", code: "alpha", clickCount: 0, isActive: true },
		];

		renderWidget();

		expect(screen.getAllByText("No clicked links yet").length).toBeGreaterThan(0);
	});
});
