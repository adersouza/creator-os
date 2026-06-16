import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MotionCard, MotionList, MotionReveal } from "./Motion";
import { ProcessingState } from "./ProcessingState";

describe("interaction polish primitives", () => {
	beforeEach(() => {
		Object.defineProperty(window, "matchMedia", {
			configurable: true,
			value: vi.fn().mockImplementation((query: string) => ({
				matches: false,
				media: query,
				onchange: null,
				addListener: vi.fn(),
				removeListener: vi.fn(),
				addEventListener: vi.fn(),
				removeEventListener: vi.fn(),
				dispatchEvent: vi.fn(),
			})),
		});
	});

	it("renders reveal content", () => {
		render(
			<MotionReveal>
				<span>Daily performance</span>
			</MotionReveal>,
		);

		expect(screen.getByText("Daily performance")).toBeInTheDocument();
	});

	it("renders static content when motion is disabled", () => {
		render(
			<MotionList disabled>
				<span>Views</span>
				<span>Reach</span>
			</MotionList>,
		);

		expect(screen.getByText("Views")).toBeInTheDocument();
		expect(screen.getByText("Reach")).toBeInTheDocument();
	});

	it("renders motion card content", () => {
		render(
			<MotionCard interactive>
				<button type="button">Open post</button>
			</MotionCard>,
		);

		expect(screen.getByRole("button", { name: "Open post" })).toBeInTheDocument();
	});

	it("exposes accessible processing status text", () => {
		render(
			<ProcessingState
				label="Generating caption"
				description="AI is preparing a safer draft."
			/>,
		);

		expect(screen.getByRole("status")).toHaveTextContent("Generating caption");
		expect(screen.getByText("AI is preparing a safer draft.")).toBeInTheDocument();
	});
});
