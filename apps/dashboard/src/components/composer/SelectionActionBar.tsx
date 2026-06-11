import { useEffect } from "react";
import { Button } from "@/components/ui/Button";
import type { ComposerAction } from "@/services/ai";

const ACTIONS: Array<{ label: string; action: ComposerAction | "custom" }> = [
	{ label: "Rewrite", action: "rephrase" },
	{ label: "Shorten", action: "shorten" },
	{ label: "Expand", action: "expand" },
	{ label: "Match voice", action: "matchVoice" },
	{ label: "Translate", action: "translate" },
	{ label: "Spin variant", action: "spin" },
	{ label: "Custom prompt", action: "custom" },
];

export function SelectionActionBar({
	open,
	anchor,
	onRun,
	onClose,
}: {
	open: boolean;
	anchor: { x: number; y: number } | null;
	onRun: (action: ComposerAction | "custom") => void;
	onClose: () => void;
}) {
	useEffect(() => {
		if (!open) return;
		const onKeyDown = (event: KeyboardEvent) => {
			if (event.key === "Escape") onClose();
		};
		window.addEventListener("keydown", onKeyDown);
		return () => window.removeEventListener("keydown", onKeyDown);
	}, [onClose, open]);

	if (!open || !anchor) return null;
	return (
		<div
			role="toolbar"
			aria-label="Selection actions"
			className="fixed z-[121] flex max-w-[calc(100vw-24px)] flex-wrap items-center gap-1 rounded-lg border border-border bg-card p-1 td-popover-shadow"
			style={{ left: anchor.x, top: anchor.y }}
		>
			{ACTIONS.map((item) => (
				<Button
					key={item.action}
					type="button"
					variant="ghost"
					size="sm"
					onClick={() => onRun(item.action)}
					className="h-7 px-2.5 text-[0.71875rem]"
				>
					{item.label}
				</Button>
			))}
		</div>
	);
}
