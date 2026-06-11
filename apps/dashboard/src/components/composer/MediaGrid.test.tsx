import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/Tooltip";
import { MediaGrid } from "./MediaGrid";

vi.mock("@/hooks/useVisionScore", () => ({
	useVisionScore: () => ({
		scores: {},
		loading: {},
		scoreImage: vi.fn(),
	}),
}));

vi.mock("@/hooks/useAltTextGenerator", () => ({
	useAltTextGenerator: () => ({
		loading: {},
		generateAltText: vi.fn(),
	}),
}));

const baseProps = {
	media: [],
	onReorder: vi.fn(),
	libraryMedia: null,
	editingAltId: null,
	editingAltItem: null,
	altDraft: "",
	onAltDraftChange: vi.fn(),
	onBeginEditAlt: vi.fn(),
	onSaveAlt: vi.fn(),
	onCancelAlt: vi.fn(),
	onAltGenerated: vi.fn(),
	onRemoveMedia: vi.fn(),
	onMoveMedia: vi.fn(),
	onOpenPicker: vi.fn(),
	fileInputRef: { current: null },
};

describe("MediaGrid", () => {
	it("accepts files dropped onto the media card", () => {
		const onFilesSelected = vi.fn();
		const file = new File(["image-bytes"], "launch.png", {
			type: "image/png",
		});
		render(
			<MediaGrid {...baseProps} onFilesSelected={onFilesSelected} />,
		);
		const mediaCard = screen.getByRole("region", { name: "Media upload" });

		fireEvent.dragEnter(mediaCard, {
			dataTransfer: { files: [file], types: ["Files"] },
		});

		expect(screen.getByText("Drop media to upload")).toBeInTheDocument();

		fireEvent.drop(mediaCard, {
			dataTransfer: { files: [file], types: ["Files"] },
		});

		expect(onFilesSelected).toHaveBeenCalledOnce();
		expect(onFilesSelected.mock.calls[0]?.[0]).toEqual([file]);
		expect(screen.queryByText("Drop media to upload")).not.toBeInTheDocument();
	});

	it("offers keyboard-friendly media reorder buttons", () => {
		const onMoveMedia = vi.fn();
		render(
			<TooltipProvider>
				<MediaGrid
					{...baseProps}
					media={[
						{
							id: "one",
							kind: "image",
							name: "one.png",
							from: "#111",
							to: "#333",
							alt: "",
						},
						{
							id: "two",
							kind: "image",
							name: "two.png",
							from: "#222",
							to: "#444",
							alt: "",
						},
					]}
					onMoveMedia={onMoveMedia}
					onFilesSelected={vi.fn()}
				/>
			</TooltipProvider>,
		);

		fireEvent.click(screen.getByLabelText("Move two.png left"));
		expect(onMoveMedia).toHaveBeenCalledWith("two", -1);
	});
});
