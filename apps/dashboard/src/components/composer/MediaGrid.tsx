import {
	Plus,
	X,
	Sparkles,
	Info,
	Play,
	Image as ImageIcon,
	Check,
	Eye,
	Wand2,
	ChevronLeft,
	ChevronRight,
} from "lucide-react";
import { useRef, useState, type DragEvent, type RefObject } from "react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Progress } from "@/components/ui/Progress";
import { IconTooltipButton } from "@/components/ui/IconTooltipButton";
import { Kbd } from "@/components/ui/Kbd";
import { Textarea } from "@/components/ui/Textarea";
import { UploadZone } from "@/components/ui/Upload";
import type { MediaItem } from "@/components/composer/PreviewSection";
import { appToast } from "@/lib/toast";
import { useAltTextGenerator } from "@/hooks/useAltTextGenerator";
import { useVisionScore, type VisionScore } from "@/hooks/useVisionScore";

/* =========================================================================
   MediaGrid — horizontal scrollable thumb strip with drag-to-reorder,
   native picker trigger, and inline alt-text editor. All state lives in
   the parent; this component is pure UI + callbacks.
   ========================================================================= */

interface ComposerMediaHandoff {
	id: string;
	name: string;
	type: "photo" | "video" | "reel";
	platforms: Array<"threads" | "instagram">;
}

export function MediaGrid({
	media,
	libraryMedia,
	editingAltId,
	editingAltItem,
	altDraft,
	onAltDraftChange,
	onBeginEditAlt,
	onSaveAlt,
	onCancelAlt,
	onAltGenerated,
	onRemoveMedia,
	onMoveMedia,
	onOpenPicker,
	onFilesSelected,
	fileInputRef,
	visionPlatform = "instagram",
}: {
	media: MediaItem[];
	onReorder: (next: MediaItem[]) => void;
	libraryMedia: ComposerMediaHandoff | null;
	editingAltId: string | null;
	editingAltItem: MediaItem | null;
	altDraft: string;
	onAltDraftChange: (v: string) => void;
	onBeginEditAlt: (id: string) => void;
	onSaveAlt: () => void;
	onCancelAlt: () => void;
	onAltGenerated: (id: string, alt: string) => void;
	onRemoveMedia: (id: string) => void;
	onMoveMedia: (id: string, direction: -1 | 1) => void;
	onOpenPicker: () => void;
	onFilesSelected: (files: FileList | null) => void;
	fileInputRef: RefObject<HTMLInputElement | null>;
	visionPlatform?: "instagram" | "threads" | undefined;
}) {
	const [dragActive, setDragActive] = useState(false);
	const dragDepthRef = useRef(0);
	const { scores, loading: scoreLoading, scoreImage } = useVisionScore();
	const { loading: altLoading, generateAltText } = useAltTextGenerator();
	const editingScore = editingAltItem?.url
		? scores[editingAltItem.url]
		: undefined;
	const editingScoreLoading = editingAltItem?.url
		? Boolean(scoreLoading[editingAltItem.url])
		: false;
	const canScoreEditing =
		Boolean(editingAltItem?.url) &&
		editingAltItem?.kind === "image" &&
		!editingAltItem?.uploading;
	const canGenerateAlt =
		Boolean(editingAltItem?.url) &&
		editingAltItem?.kind === "image" &&
		!editingAltItem?.uploading;
	const generatingAlt = editingAltItem?.url
		? Boolean(altLoading[editingAltItem.url])
		: false;
	const uploadingCount = media.filter((item) => item.uploading).length;
	const uploadCapacity = Math.round((media.length / 10) * 100);

	const runGenerateAlt = async () => {
		if (!editingAltItem?.url || editingAltItem.kind !== "image") return;
		const result = await generateAltText({
			imageUrl: editingAltItem.url,
			platform: visionPlatform,
			postType: visionPlatform === "instagram" ? "feed" : "post",
		});
		if (!result?.altText) {
			appToast.error("Could not generate alt text");
			return;
		}
		onAltDraftChange(result.altText);
		onAltGenerated(editingAltItem.id, result.altText);
		appToast.success("Alt text generated");
	};

	const hasFileDrag = (event: DragEvent<HTMLElement>) =>
		Array.from(event.dataTransfer.types).includes("Files");

	const handleDragEnter = (event: DragEvent<HTMLElement>) => {
		if (!hasFileDrag(event)) return;
		event.preventDefault();
		event.stopPropagation();
		dragDepthRef.current += 1;
		setDragActive(true);
	};

	const handleDragOver = (event: DragEvent<HTMLElement>) => {
		if (!hasFileDrag(event)) return;
		event.preventDefault();
		event.stopPropagation();
		event.dataTransfer.dropEffect = media.length < 10 ? "copy" : "none";
		setDragActive(true);
	};

	const handleDragLeave = (event: DragEvent<HTMLElement>) => {
		if (!hasFileDrag(event)) return;
		event.preventDefault();
		event.stopPropagation();
		dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
		if (dragDepthRef.current === 0) setDragActive(false);
	};

	const handleDrop = (event: DragEvent<HTMLElement>) => {
		if (!hasFileDrag(event)) return;
		event.preventDefault();
		event.stopPropagation();
		dragDepthRef.current = 0;
		setDragActive(false);
		onFilesSelected(event.dataTransfer.files);
	};

	return (
		<NovaCard
			role="region"
			aria-label="Media upload"
			title="Media"
			description="Add images or video, reorder them, and keep accessibility text close to the asset."
			action={
				<div className="flex items-center gap-2">
					{libraryMedia ? (
						<Badge tone="oxblood">
							<Sparkles data-icon="inline-start" aria-hidden="true" />
							From library
						</Badge>
					) : null}
					<Badge tone={uploadingCount > 0 ? "oxblood" : "outline"}>
						{uploadingCount > 0
							? `${uploadingCount} uploading`
							: `${media.length} / 10`}
					</Badge>
				</div>
			}
			footer={
				<div className="flex min-w-0 flex-col gap-2 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
					<span className="inline-flex min-w-0 items-center gap-1.5">
						<Info data-icon="inline-start" aria-hidden="true" />
						<span className="truncate">
							Drop files here, use Add, then reorder or write alt text per asset.
						</span>
					</span>
					<span className="shrink-0 tabular-nums">
						{media.length} of 10 attached
					</span>
				</div>
			}
			onDragEnter={handleDragEnter}
			onDragOver={handleDragOver}
			onDragLeave={handleDragLeave}
			onDrop={handleDrop}
			className={cn(
				"relative scroll-mb-28 transition-colors lg:scroll-mb-0",
				dragActive
					? "border-[color-mix(in_srgb,var(--color-oxblood)_52%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-oxblood)_5%,var(--color-card))]"
					: "",
			)}
		>
			{dragActive && (
				<div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center rounded-[inherit] border-2 border-dashed border-[color-mix(in_srgb,var(--color-oxblood)_58%,transparent)] bg-[color-mix(in_srgb,var(--color-card)_86%,transparent)] backdrop-blur-[2px]">
					<div className="flex flex-col items-center gap-1.5 text-center">
						<Plus
							className="h-5 w-5 text-[color:var(--color-oxblood)]"
							aria-hidden="true"
						/>
						<span className="text-[0.8125rem] font-semibold text-foreground">
							Drop media to upload
						</span>
						<span className="text-[0.6875rem] text-muted-foreground">
							Images or videos · {media.length} / 10 attached
						</span>
					</div>
				</div>
			)}
			<div className="grid gap-3">
				<div className="grid gap-2">
					<Progress
						value={uploadCapacity}
						aria-label="Media attachment capacity"
						tone={media.length >= 10 ? "warn" : "default"}
					/>
					<div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
						<span>
							{uploadingCount > 0
								? "Uploads are still processing."
								: media.length === 0
									? "No media attached yet."
									: "Media ready for this draft."}
						</span>
						<span className="shrink-0 tabular-nums">{uploadCapacity}% used</span>
					</div>
				</div>

				{media.length === 0 ? (
					<UploadZone
						onClick={onOpenPicker}
						title="Drop media here or choose files"
						description="Images, videos, and reels stay attached to the current draft. Validation runs before upload."
						helper={`${media.length} / 10 attached`}
						actionLabel="Choose media"
						className="min-h-[132px] md:min-h-[178px]"
					/>
				) : (
					<div className="rounded-lg border border-border bg-muted/25 p-2">
						<div className="flex items-start gap-2 overflow-x-auto hide-scrollbar pb-1">
							{media.map((m) => (
								<div key={m.id} className="shrink-0">
									<MediaThumb
										item={m}
										editing={editingAltId === m.id}
										canMoveLeft={media.findIndex((item) => item.id === m.id) > 0}
										canMoveRight={
											media.findIndex((item) => item.id === m.id) <
											media.length - 1
										}
										onRemove={() => onRemoveMedia(m.id)}
										onMoveLeft={() => onMoveMedia(m.id, -1)}
										onMoveRight={() => onMoveMedia(m.id, 1)}
										onEditAlt={() => onBeginEditAlt(m.id)}
									/>
								</div>
							))}

							{media.length < 10 && (
								<Button
									type="button"
									variant="outline"
									onClick={onOpenPicker}
									className="h-20 w-20 shrink-0 flex-col gap-1 border-dashed text-muted-foreground hover:text-foreground"
								>
									<Plus data-icon="stacked" aria-hidden="true" />
									<span className="text-[0.65625rem] font-medium">Add</span>
								</Button>
							)}
						</div>
					</div>
				)}
			</div>
			<input
				ref={fileInputRef}
				type="file"
				accept="image/*,video/*"
				multiple
				className="hidden"
				onChange={(e) => onFilesSelected(e.target.files)}
			/>

			<div
				className={cn(
					"grid transition-[grid-template-rows,opacity,margin-top] duration-[220ms] ease-[cubic-bezier(0.23,1,0.32,1)]",
					editingAltItem
						? "grid-rows-[1fr] opacity-100 mt-3"
						: "grid-rows-[0fr] opacity-0 mt-0",
				)}
				aria-hidden={!editingAltItem}
			>
				<div className="overflow-hidden">
					{editingAltItem && (
						<div
							key={editingAltItem.id}
							className="rounded-md border border-[var(--color-ring-oxblood)] bg-[color-mix(in_srgb,var(--color-oxblood)_5%,transparent)] p-3 flex gap-3"
						>
							<div
								className="w-12 h-12 rounded-md shrink-0 border border-border"
								style={{
									background: `linear-gradient(135deg, ${editingAltItem.from}, ${editingAltItem.to})`,
								}}
								aria-hidden="true"
							/>
							<div className="flex-1 min-w-0">
								<div className="flex items-baseline justify-between gap-2 mb-1.5">
									<span
										className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em]"
										style={{ color: "var(--color-oxblood)" }}
									>
										Alt text · {editingAltItem.name}
									</span>
									<span className="text-[0.65625rem] tabular-nums text-muted-foreground">
										{altDraft.length} / 100
									</span>
								</div>
								<Textarea
									value={altDraft}
									maxLength={100}
									onChange={(e) => onAltDraftChange(e.target.value)}
									onKeyDown={(e) => {
										if (e.key === "Escape") {
											e.preventDefault();
											onCancelAlt();
										} else if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
											e.preventDefault();
											onSaveAlt();
										}
									}}
									placeholder="Describe what's in the image for people using screen readers…"
									rows={2}
									className="min-h-16 resize-none"
								/>
								<div className="mt-2 flex items-center gap-1.5">
									{canGenerateAlt && (
										<Button
											type="button"
											onClick={() => void runGenerateAlt()}
											disabled={generatingAlt}
											variant="outline"
											size="sm"
											className="text-[color:var(--color-oxblood)]"
										>
											<span className="inline-flex items-center gap-1.5">
												<Wand2 data-icon="inline-start" aria-hidden="true" />
												{generatingAlt ? "Generating…" : "Generate alt"}
											</span>
										</Button>
									)}
									<Button type="button" onClick={onSaveAlt} size="sm">
										Save
									</Button>
									<Button
										type="button"
										onClick={onCancelAlt}
										variant="ghost"
										size="sm"
									>
										Cancel
									</Button>
									<span className="ml-auto inline-flex items-center gap-2 text-[0.65625rem] text-muted-foreground">
										<span className="inline-flex items-center gap-1">
											<Kbd>⌘</Kbd>
											<Kbd>↵</Kbd>
											save
										</span>
										<span className="inline-flex items-center gap-1">
											<Kbd>Esc</Kbd>
											cancel
										</span>
									</span>
								</div>
								{canScoreEditing && (
									<VisionScoreBlock
										item={editingAltItem}
										score={editingScore}
										loading={editingScoreLoading}
										onScore={() => {
											if (editingAltItem.url) {
												void scoreImage(editingAltItem.url, visionPlatform);
											}
										}}
									/>
								)}
							</div>
						</div>
					)}
				</div>
			</div>
		</NovaCard>
	);
}

const VISION_DIMENSIONS: Array<{
	key: keyof VisionScore["breakdown"];
	label: string;
}> = [
	{ key: "composition", label: "Composition" },
	{ key: "lighting", label: "Lighting" },
	{ key: "color", label: "Color" },
	{ key: "clarity", label: "Clarity" },
	{ key: "engagement_potential", label: "Engagement" },
];

function scoreColor(score: number): string {
	if (score >= 71) return "var(--color-health-good)";
	if (score >= 41) return "var(--color-gold)";
	return "var(--color-oxblood)";
}

function VisionScoreBlock({
	item,
	score,
	loading,
	onScore,
}: {
	item: MediaItem;
	score: VisionScore | undefined;
	loading: boolean;
	onScore: () => void;
}) {
	if (!score && !loading) {
		return (
			<div className="mt-3 pt-3 border-t border-dashed border-[var(--color-ring-oxblood)]">
				<Button
					type="button"
					onClick={onScore}
					variant="ghost"
					size="sm"
					className="h-7 gap-1.5 px-0 text-[0.71875rem]"
					aria-label={`Get AI vision score for ${item.name}`}
				>
					<Eye data-icon="inline-start" aria-hidden="true" />
					Score this image
				</Button>
			</div>
		);
	}
	if (loading) {
		return (
			<div className="mt-3 pt-3 border-t border-dashed border-[var(--color-ring-oxblood)] text-[0.71875rem] text-muted-foreground inline-flex items-center gap-1.5">
				<Eye className="w-3 h-3 animate-pulse" aria-hidden="true" />
				Scoring image…
			</div>
		);
	}
	if (!score) return null;
	return (
		<div className="mt-3 pt-3 border-t border-dashed border-[var(--color-ring-oxblood)]">
			<div className="flex items-baseline justify-between mb-2">
				<span
					className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em]"
					style={{ color: "var(--color-oxblood)" }}
				>
					AI vision score
				</span>
				<span
					className="text-[0.875rem] font-semibold tabular-nums"
					style={{ color: scoreColor(score.score) }}
				>
					{Math.round(score.score)}
					<span className="text-muted-foreground text-[0.6875rem] font-normal">
						{" "}
						/ 100
					</span>
				</span>
			</div>
			<div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
				{VISION_DIMENSIONS.map((d) => {
					const value = score.breakdown[d.key] ?? 0;
					return (
						<div key={d.key} className="flex flex-col gap-0.5">
							<div className="flex items-center justify-between text-[0.65625rem]">
								<span className="text-muted-foreground uppercase tracking-[0.04em]">
									{d.label}
								</span>
								<span
									className="font-mono tabular-nums text-muted-foreground"
									style={{ color: scoreColor(value) }}
								>
									{Math.round(value)}
								</span>
							</div>
							<div className="h-[3px] rounded-full bg-border overflow-hidden">
								<div
									className="h-full rounded-full"
									style={{
										width: `${Math.max(4, Math.min(100, value))}%`,
										background: scoreColor(value),
									}}
								/>
							</div>
						</div>
					);
				})}
			</div>
			{score.suggestions.length > 0 && (
				<ul className="mt-3 flex flex-col gap-1">
					{score.suggestions.slice(0, 3).map((s, i) => (
						<li
							key={i}
							className="text-[0.71875rem] text-muted-foreground leading-snug pl-3 relative"
						>
							<span
								className="absolute left-0 top-[0.5em] w-1 h-1 rounded-full"
								style={{ background: "var(--color-oxblood)" }}
								aria-hidden="true"
							/>
							{s}
						</li>
					))}
				</ul>
			)}
		</div>
	);
}

function MediaThumb({
	item,
	editing,
	canMoveLeft,
	canMoveRight,
	onRemove,
	onMoveLeft,
	onMoveRight,
	onEditAlt,
}: {
	item: MediaItem;
	editing: boolean;
	canMoveLeft: boolean;
	canMoveRight: boolean;
	onRemove: () => void;
	onMoveLeft: () => void;
	onMoveRight: () => void;
	onEditAlt: () => void;
}) {
	const altSet = item.alt.trim().length > 0;
	return (
		<div
			className={cn(
				"relative w-20 h-20 rounded-md overflow-hidden border cursor-grab active:cursor-grabbing transition-shadow",
				editing
					? "border-[var(--color-ring-oxblood-strong)] shadow-[0_0_0_2px_var(--color-ring-oxblood)]"
					: "border-border",
			)}
			style={
				item.url
					? undefined
					: { background: `linear-gradient(135deg, ${item.from}, ${item.to})` }
			}
			title={altSet ? `Alt: ${item.alt}` : item.name}
		>
			{item.url && item.kind === "image" && (
				<img
					src={item.url}
					alt={item.alt || ""}
					loading="lazy"
					decoding="async"
					className="absolute inset-0 w-full h-full object-cover"
				/>
			)}
			{item.url && item.kind === "video" && (
				<video
					src={item.url}
					className="absolute inset-0 w-full h-full object-cover"
					muted
					playsInline
					preload="metadata"
				/>
			)}
			{item.uploading && (
				<div className="absolute inset-0 bg-[color-mix(in_srgb,var(--color-foreground)_55%,transparent)] backdrop-blur-sm inline-flex items-center justify-center">
					<span className="text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-white">
						Uploading…
					</span>
				</div>
			)}
			<div className="absolute top-1 left-1 inline-flex items-center justify-center w-4 h-4 rounded-[3px] bg-[color-mix(in_srgb,var(--color-foreground)_50%,transparent)] backdrop-blur-sm">
				{item.kind === "video" ? (
					<Play
						className="w-2.5 h-2.5 text-white fill-white"
						aria-hidden="true"
					/>
				) : (
					<ImageIcon className="w-2.5 h-2.5 text-white" aria-hidden="true" />
				)}
			</div>
			<IconTooltipButton
				label="Remove media"
				onClick={(e) => {
					e.stopPropagation();
					onRemove();
				}}
				className="absolute top-0 right-0"
				side="left"
			>
				<span className="w-5 h-5 rounded-full bg-[color-mix(in_srgb,var(--color-foreground)_60%,transparent)] backdrop-blur-sm text-white inline-flex items-center justify-center hover:bg-[color-mix(in_srgb,var(--color-foreground)_80%,transparent)] transition-colors">
					<X className="w-2.5 h-2.5" aria-hidden="true" />
				</span>
			</IconTooltipButton>
			<div className="absolute bottom-1 right-1 inline-flex items-center gap-0.5">
				<Button
					type="button"
					variant="ghost"
					onPointerDown={(e) => e.stopPropagation()}
					onClick={(e) => {
						e.stopPropagation();
						onMoveLeft();
					}}
					disabled={!canMoveLeft}
					aria-label={`Move ${item.name} left`}
					className="h-5 w-5 rounded-[3px] bg-[color-mix(in_srgb,var(--color-foreground)_52%,transparent)] p-0 text-white backdrop-blur-sm hover:bg-[color-mix(in_srgb,var(--color-foreground)_78%,transparent)] disabled:opacity-35"
				>
					<ChevronLeft className="h-3 w-3" aria-hidden="true" />
				</Button>
				<Button
					type="button"
					variant="ghost"
					onPointerDown={(e) => e.stopPropagation()}
					onClick={(e) => {
						e.stopPropagation();
						onMoveRight();
					}}
					disabled={!canMoveRight}
					aria-label={`Move ${item.name} right`}
					className="h-5 w-5 rounded-[3px] bg-[color-mix(in_srgb,var(--color-foreground)_52%,transparent)] p-0 text-white backdrop-blur-sm hover:bg-[color-mix(in_srgb,var(--color-foreground)_78%,transparent)] disabled:opacity-35"
				>
					<ChevronRight className="h-3 w-3" aria-hidden="true" />
				</Button>
			</div>
			<Button
				type="button"
				variant="ghost"
				onPointerDown={(e) => e.stopPropagation()}
				onClick={(e) => {
					e.stopPropagation();
					onEditAlt();
				}}
				aria-label={altSet ? "Edit alt text" : "Add alt text"}
				title={altSet ? "Edit alt text" : "Add alt text"}
				className={cn(
					"absolute bottom-1 left-1 h-4 px-1.5 rounded-[3px] text-[0.5625rem] font-semibold uppercase tracking-[0.08em] backdrop-blur-sm",
					altSet
						? "text-white bg-[color-mix(in_srgb,var(--color-oxblood)_82%,transparent)] hover:bg-[color-mix(in_srgb,var(--color-oxblood)_95%,transparent)]"
						: "text-white/80 bg-[color-mix(in_srgb,var(--color-foreground)_50%,transparent)] hover:bg-[color-mix(in_srgb,var(--color-foreground)_70%,transparent)] hover:text-white",
				)}
			>
				{altSet ? (
					<span className="inline-flex items-center gap-0.5">
						<Check className="w-2 h-2" aria-hidden="true" />
						Alt
					</span>
				) : (
					"Alt"
				)}
			</Button>
		</div>
	);
}
