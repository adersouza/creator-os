import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
	AnalyticsSkeleton,
	BillingSkeleton,
	ComposerSkeleton,
	DashboardSkeleton,
	SettingsSkeleton,
} from "./PageSkeletons";

const legacyClassPattern =
	/(^|\s)(card|operator-page|operator-material|settings-page)(\s|$)|(^|\s)(dv2-|j33-)/;

function expectNoLegacyClasses(container: HTMLElement) {
	const legacyClasses = Array.from(container.querySelectorAll("[class]"))
		.map((element) => element.getAttribute("class") ?? "")
		.filter((className) => legacyClassPattern.test(className));

	expect(legacyClasses).toEqual([]);
}

describe("page skeletons", () => {
	it("renders dashboard and analytics loading surfaces without legacy classes", () => {
		const { container, rerender } = render(<DashboardSkeleton />);

		expect(screen.getAllByLabelText("Loading dashboard")).toHaveLength(2);
		expectNoLegacyClasses(container);

		rerender(<AnalyticsSkeleton />);

		expect(screen.getByLabelText("Loading analytics")).toBeInTheDocument();
		expectNoLegacyClasses(container);
	});

	it("renders operational route skeletons without legacy classes", () => {
		const { container, rerender } = render(<ComposerSkeleton />);

		expect(screen.getByLabelText("Loading composer")).toBeInTheDocument();
		expectNoLegacyClasses(container);

		rerender(<BillingSkeleton />);
		expect(screen.getByLabelText("Loading billing")).toBeInTheDocument();
		expectNoLegacyClasses(container);

		rerender(<SettingsSkeleton />);
		expect(screen.getByLabelText("Loading settings")).toBeInTheDocument();
		expectNoLegacyClasses(container);
	});
});
