import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Textarea } from "@/components/ui/Textarea";
import {
	fetchVoiceContextFile,
	saveVoiceContextFile,
} from "@/services/api/composer";
import { Loader2 } from "lucide-react";

export function VoiceContextFile({
	open,
	groupId,
	onClose,
}: {
	open: boolean;
	groupId: string | null;
	onClose: () => void;
}) {
	const [content, setContent] = useState("");
	const [saving, setSaving] = useState(false);
	const [loading, setLoading] = useState(false);

	useEffect(() => {
		if (!open || !groupId) return;
		let cancelled = false;
		setLoading(true);
		fetchVoiceContextFile(groupId)
			.then((file) => {
				if (!cancelled) setContent(file.content ?? "");
			})
			.catch(() => {
				if (!cancelled) setContent("");
			})
			.finally(() => {
				if (!cancelled) setLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [groupId, open]);

	const save = async () => {
		if (!groupId) return;
		setSaving(true);
		try {
			await saveVoiceContextFile(groupId, content);
			onClose();
		} finally {
			setSaving(false);
		}
	};

	return (
		<Modal
			open={open}
			onClose={onClose}
			title="Voice file"
			description="Edit the voice context used by Composer AI actions."
			maxWidthClass="max-w-2xl"
			footer={
				<>
					<Button type="button" onClick={onClose} variant="ghost">
						Cancel
					</Button>
					<Button
						type="button"
						onClick={save}
						disabled={!groupId || saving || loading}
						className="gap-1.5"
					>
						{saving ? (
							<Loader2
								className="h-3.5 w-3.5 animate-spin"
								aria-hidden="true"
							/>
						) : null}
						{saving ? "Saving" : "Save"}
					</Button>
				</>
			}
		>
			{loading ? (
				<div
					role="status"
					aria-live="polite"
					className="mb-2 text-[0.75rem] text-muted-foreground"
				>
					Loading voice file
				</div>
			) : null}
			<Textarea
				value={content}
				onChange={(event) => setContent(event.target.value)}
				disabled={loading}
				rows={14}
				className="font-mono"
			/>
		</Modal>
	);
}
