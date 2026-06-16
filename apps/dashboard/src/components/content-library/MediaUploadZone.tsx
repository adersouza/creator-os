import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { Select } from "@/components/ui/Select";
import { UploadStatusList, UploadZone } from "@/components/ui/Upload";
import { supabase } from "@/services/supabase";
import { registerUploadedMedia } from "@/services/api/contentLibrary";
import { invalidateMediaCache } from "@/services/mediaService";
import type { LibraryAccount, LibraryGroup, PlatformKind } from "./types";

const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
const ACCEPTED_TYPES = new Set([
	"image/jpeg",
	"image/png",
	"image/gif",
	"image/webp",
	"video/mp4",
	"video/quicktime",
	"video/webm",
]);

function safeName(file: File) {
	const ext = file.name.split(".").pop() || "bin";
	const base = file.name
		.replace(/\.[^.]+$/, "")
		.replace(/[^a-zA-Z0-9_-]+/g, "-")
		.slice(0, 40);
	return `${base || "upload"}.${ext}`;
}

const accountOptionLabel = (account: LibraryAccount) =>
	`${account.handle} · ${account.platform === "instagram" ? "IG" : "Threads"}`;

export function MediaUploadZone({
	open,
	onClose,
	onComplete,
	groups,
	accounts,
}: {
	open: boolean;
	onClose: () => void;
	onComplete: () => void;
	groups: LibraryGroup[];
	accounts: LibraryAccount[];
}) {
	const inputRef = useRef<HTMLInputElement>(null);
	const closeTimerRef = useRef<number | null>(null);
	const [progress, setProgress] = useState(0);
	const [isUploading, setIsUploading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [uploadName, setUploadName] = useState<string | null>(null);
	const [groupId, setGroupId] = useState("unassigned");
	const [accountKey, setAccountKey] = useState("unassigned");

	const scopedAccounts =
		groupId === "unassigned"
			? accounts
			: accounts.filter((account) => account.groupId === groupId);

	useEffect(() => {
		return () => {
			if (closeTimerRef.current != null) {
				window.clearTimeout(closeTimerRef.current);
			}
		};
	}, []);

	useEffect(() => {
		if (open) return;
		if (closeTimerRef.current != null) {
			window.clearTimeout(closeTimerRef.current);
			closeTimerRef.current = null;
		}
		setProgress(0);
		setIsUploading(false);
		setError(null);
		setUploadName(null);
		setGroupId("unassigned");
		setAccountKey("unassigned");
	}, [open]);

	useEffect(() => {
		if (accountKey === "unassigned") return;
		const [, accountId] = accountKey.split(":") as [PlatformKind, string];
		if (!scopedAccounts.some((account) => account.id === accountId)) {
			setAccountKey("unassigned");
		}
	}, [accountKey, scopedAccounts]);

	const uploadFiles = async (files: FileList | File[]) => {
		const file = Array.from(files)[0];
		if (!file) return;
		setError(null);
		setUploadName(file.name);
		if (!ACCEPTED_TYPES.has(file.type)) {
			setError("Use JPG, PNG, GIF, WebP, MP4, MOV, or WebM.");
			return;
		}
		if (file.size > MAX_UPLOAD_BYTES) {
			setError("Media uploads are limited to 50MB.");
			return;
		}
		setIsUploading(true);
		setProgress(12);
		try {
			const {
				data: { user },
			} = await supabase.auth.getUser();
			if (!user) throw new Error("Not authenticated");
			const storagePath = `${user.id}/${Date.now()}-${safeName(file)}`;
			const [accountPlatform, accountId] =
				accountKey === "unassigned"
					? [null, null]
					: (accountKey.split(":") as [PlatformKind, string]);
			const { error: uploadError } = await supabase.storage
				.from("media")
				.upload(storagePath, file, {
					cacheControl: "3600",
					upsert: false,
					...(file.type ? { contentType: file.type } : {}),
				});
			if (uploadError) throw uploadError;
			setProgress(72);
			const { data } = supabase.storage.from("media").getPublicUrl(storagePath);
			await registerUploadedMedia({
				fileName: file.name,
				fileUrl: data.publicUrl,
				storagePath,
				mimeType: file.type,
				fileSize: file.size,
				groupId: groupId === "unassigned" ? null : groupId,
				accountId,
				accountPlatform,
			});
			invalidateMediaCache(user.id);
			setProgress(100);
			onComplete();
			if (closeTimerRef.current != null) {
				window.clearTimeout(closeTimerRef.current);
			}
			closeTimerRef.current = window.setTimeout(() => {
				setProgress(0);
				setIsUploading(false);
				closeTimerRef.current = null;
				onClose();
			}, 450);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Upload failed");
			setIsUploading(false);
		}
	};

	if (!open) return null;

	return (
		<Modal
			open={open}
			onClose={() => {
				if (!isUploading) onClose();
			}}
			title="Upload media"
			description="Add a photo or video to the shared library."
			maxWidthClass="max-w-[520px]"
			bodyClassName="p-4"
			disablePanelBlur
			hideCloseButton={isUploading}
			footer={
				<Button
					type="button"
					onClick={onClose}
					disabled={isUploading}
					variant="outline"
					size="sm"
				>
					<X data-icon="inline-start" aria-hidden="true" />
					Close
				</Button>
			}
		>
			<UploadZone
				disabled={isUploading}
				title="Drop files here or click to select"
				description="Add media to the shared library and assign it to a group or creator."
				helper="JPG, PNG, GIF, WebP, MP4, MOV, or WebM up to 50MB."
				actionLabel="Choose media"
				inputRef={inputRef}
				accept="image/jpeg,image/png,image/gif,image/webp,video/mp4,video/quicktime,video/webm"
				onFilesSelected={(files) => {
					if (files) void uploadFiles(files);
				}}
				onDropFiles={(files) => void uploadFiles(files)}
			/>
			<div className="mt-4 grid gap-3 sm:grid-cols-2">
				<Field label="Group">
					<Select
						id="media-upload-group"
						value={groupId}
						onChange={(event) => setGroupId(event.target.value)}
						disabled={isUploading}
						aria-label="Group"
					>
						<option value="unassigned">Unassigned</option>
						{groups.map((group) => (
							<option key={group.id} value={group.id}>
								{group.name}
							</option>
						))}
					</Select>
				</Field>
				<Field label="Creator">
					<Select
						id="media-upload-creator"
						value={accountKey}
						onChange={(event) => setAccountKey(event.target.value)}
						disabled={isUploading}
						aria-label="Creator"
					>
						<option value="unassigned">No creator</option>
						{scopedAccounts.map((account) => (
							<option
								key={`${account.platform}:${account.id}`}
								value={`${account.platform}:${account.id}`}
							>
								{accountOptionLabel(account)}
							</option>
						))}
					</Select>
				</Field>
			</div>
			{(isUploading || progress > 0 || error) && (
				<UploadStatusList
					className="mt-4"
					showSections={false}
					items={[
						{
							id: "library-upload",
							name: uploadName ?? "Media upload",
							description:
								error ??
								(progress >= 100
									? "Upload complete"
									: "Uploading and registering this asset."),
							status: error ? "error" : progress >= 100 ? "done" : "uploading",
							progress,
						},
					]}
				/>
			)}
		</Modal>
	);
}
