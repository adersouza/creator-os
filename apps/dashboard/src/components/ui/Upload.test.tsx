import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { UploadStatusList, UploadZone } from "@/components/ui/Upload";

describe("Upload Blocks adapters", () => {
	it("opens the hidden file input and handles selected files", () => {
		const onFilesSelected = vi.fn();
		render(
			<UploadZone
				title="Upload media"
				actionLabel="Choose media"
				accept="image/png"
				onFilesSelected={onFilesSelected}
			/>,
		);

		const input = document.querySelector("input[type='file']") as HTMLInputElement;
		expect(input).toHaveClass("hidden");
		expect(input).toHaveAttribute("accept", "image/png");

		fireEvent.change(input, {
			target: {
				files: [new File(["demo"], "demo.png", { type: "image/png" })],
			},
		});

		expect(onFilesSelected).toHaveBeenCalledOnce();
		expect(screen.getByRole("button", { name: /Upload media/i })).toBeInTheDocument();
	});

	it("handles drag and drop files", () => {
		const onDropFiles = vi.fn();
		render(<UploadZone title="Drop assets" onDropFiles={onDropFiles} />);
		const button = screen.getByRole("button", { name: /Drop assets/i });
		const file = new File(["demo"], "demo.jpg", { type: "image/jpeg" });

		fireEvent.drop(button, {
			dataTransfer: {
				files: [file],
			},
		});

		expect(onDropFiles).toHaveBeenCalledOnce();
	});

	it("renders upload status rows with progress and actions", () => {
		render(
			<UploadStatusList
				items={[
					{
						id: "one",
						name: "launch.mov",
						description: "Uploading to media library",
						status: "uploading",
						progress: 42,
						actions: <button type="button">Cancel</button>,
					},
					{
						id: "two",
						name: "ready.png",
						status: "done",
					},
				]}
			/>,
		);

		expect(screen.getByText("Active uploads")).toBeInTheDocument();
		expect(screen.getByText("Completed")).toBeInTheDocument();
		expect(screen.getByText("launch.mov")).toBeInTheDocument();
		expect(screen.getByLabelText("launch.mov upload progress")).toHaveAttribute(
			"aria-valuenow",
			"42",
		);
		expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
		expect(screen.getByText("ready.png")).toBeInTheDocument();
	});

	it("renders an accessible empty state when provided", () => {
		render(<UploadStatusList items={[]} empty={<p>No uploads</p>} />);
		expect(screen.getByText("No uploads")).toBeInTheDocument();
	});
});
