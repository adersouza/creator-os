import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Textarea } from "@/components/ui/Textarea";

export function CustomPromptModal({
	open,
	value,
	running,
	onChange,
	onClose,
	onRun,
}: {
	open: boolean;
	value: string;
	running: boolean;
	onChange: (value: string) => void;
	onClose: () => void;
	onRun: () => void;
}) {
	return (
		<Modal
			open={open}
			onClose={onClose}
			title="Custom AI prompt"
			description="Tell Juno33 exactly how to transform the selected text or caption."
			maxWidthClass="max-w-xl"
			footer={
				<>
					<Button type="button" onClick={onClose} variant="ghost">
						Cancel
					</Button>
					<Button
						type="button"
						onClick={onRun}
						disabled={!value.trim() || running}
					>
						{running ? "Running..." : "Apply prompt"}
					</Button>
				</>
			}
		>
			<Textarea
				value={value}
				onChange={(event) => onChange(event.target.value)}
				rows={5}
				placeholder="Make this more specific, keep the same voice, and add a sharper CTA."
			/>
		</Modal>
	);
}
